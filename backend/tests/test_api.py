import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.config import get_settings
from app.domain import process_job
from app.errors import ProviderError
from app.main import app
from app.models import Asset
from app.db import SessionLocal


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


def jpeg(color=(180, 150, 120), size=(640, 800)) -> bytes:
    image = Image.new("RGB", size, color)
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=90)
    return buffer.getvalue()


def auth(client: TestClient) -> dict:
    created = client.post("/api/workspaces")
    assert created.status_code == 201
    return {"X-Workspace-Token": created.json()["token"]}


def session_with_items(client: TestClient, headers: dict):
    photo = client.post("/api/photo-sessions", headers=headers, files={"file": ("person.jpg", jpeg(), "image/jpeg")})
    assert photo.status_code == 201, photo.text
    body = photo.json()
    frame = client.post(
        f"/api/photo-sessions/{body['id']}/inspiration-frames",
        headers=headers,
        files={"file": ("look.jpg", jpeg((40, 70, 90), (600, 800)), "image/jpeg")},
        data={"source_kind": "upload", "source_url": "https://example.com/watch"},
    )
    assert frame.status_code == 201, frame.text
    detected = client.post(f"/api/inspiration-frames/{frame.json()['id']}/detect", headers=headers)
    assert detected.status_code == 200, detected.text
    return body["id"], detected.json()


def item_by_prompt(frame: dict, prompt: str) -> dict:
    return next(item for item in frame["items"] if item["category_prompt"] == prompt)


def try_on(client, headers, session_id, item, key, **extra):
    session = client.get(f"/api/photo-sessions/{session_id}", headers=headers).json()
    payload = {
        "expected_revision": session["revision"],
        "idempotency_key": key,
        "origin": "inspiration",
        "item_id": item["id"],
        "gender": "female",
        "style": "random",
    }
    payload.update(extra)
    response = client.post(f"/api/photo-sessions/{session_id}/try-on", headers=headers, json=payload)
    return response


def finish(client, headers, response):
    assert response.status_code == 202, response.text
    job_id = response.json()["id"]
    process_job(job_id)
    job = client.get(f"/api/jobs/{job_id}", headers=headers)
    assert job.status_code == 200
    return job.json()


def test_category_mapping():
    from app.categories import internal_category

    assert internal_category("hat") == "hat"
    assert internal_category("Scarf") == "scarf"
    assert internal_category("shoe") == "shoes"
    assert internal_category("jacket") == "outerwear"
    assert internal_category("coat") == "outerwear"
    assert internal_category("shirt") == "upper_body"
    assert internal_category("sweater") == "upper_body"
    assert internal_category("trousers") == "lower_body"
    assert internal_category("skirt") == "lower_body"
    assert internal_category("dress") == "full_body"


def test_branching_undo_reset_reload_and_previous_sessions(client):
    headers = auth(client)
    session_id, frame = session_with_items(client, headers)
    hat = item_by_prompt(frame, "hat")
    jacket = item_by_prompt(frame, "jacket")
    shoe = item_by_prompt(frame, "shoe")

    first = finish(client, headers, try_on(client, headers, session_id, hat, "idem-hat-0001"))
    assert first["status"] == "succeeded"
    assert first["applied_to_active"] is True
    after_hat = client.get(f"/api/photo-sessions/{session_id}", headers=headers).json()
    hat_version = next(version for version in after_hat["versions"] if version["category"] == "hat")
    assert hat_version["parent_version_id"] == after_hat["root_version_id"]
    assert after_hat["active_version_id"] == hat_version["id"]

    second = finish(client, headers, try_on(client, headers, session_id, jacket, "idem-jacket-01"))
    assert second["applied_to_active"] is True
    after_jacket = client.get(f"/api/photo-sessions/{session_id}", headers=headers).json()
    jacket_version = next(version for version in after_jacket["versions"] if version["category"] == "outerwear")
    assert jacket_version["parent_version_id"] == hat_version["id"]

    chosen = client.post(f"/api/photo-sessions/{session_id}/active", headers=headers, json={"version_id": hat_version["id"]})
    assert chosen.status_code == 200
    branch = finish(client, headers, try_on(client, headers, session_id, shoe, "idem-shoes-001"))
    assert branch["status"] == "succeeded"
    branched = client.get(f"/api/photo-sessions/{session_id}", headers=headers).json()
    shoes = next(version for version in branched["versions"] if version["category"] == "shoes")
    assert shoes["parent_version_id"] == hat_version["id"]
    assert jacket_version["id"] in {version["id"] for version in branched["versions"]}
    assert branched["active_version_id"] == shoes["id"]

    undone = client.post(f"/api/photo-sessions/{session_id}/undo", headers=headers)
    assert undone.status_code == 200
    assert undone.json()["active_version_id"] == hat_version["id"]
    assert len(undone.json()["versions"]) == 4

    reset = client.post(f"/api/photo-sessions/{session_id}/reset", headers=headers)
    assert reset.json()["active_version_id"] == reset.json()["root_version_id"]
    assert len(reset.json()["versions"]) == 4

    reloaded = client.post(f"/api/photo-sessions/{session_id}/reload", headers=headers)
    assert reloaded.json()["active_version_id"] == reloaded.json()["root_version_id"]
    labels = {version["label"] for version in reloaded.json()["versions"]}
    assert {"Original", "Hat", "Outerwear", "Shoes"} <= labels

    other = client.post("/api/photo-sessions", headers=headers, files={"file": ("other.jpg", jpeg((10, 20, 30)), "image/jpeg")})
    assert other.status_code == 201
    listed = client.get("/api/photo-sessions", headers=headers)
    ids = {item["id"] for item in listed.json()["sessions"]}
    assert session_id in ids
    assert other.json()["id"] in ids


def test_stale_success_does_not_replace_active_selection(client):
    headers = auth(client)
    session_id, frame = session_with_items(client, headers)
    hat = item_by_prompt(frame, "hat")
    started = try_on(client, headers, session_id, hat, "idem-stale-0001")
    assert started.status_code == 202
    reloaded = client.post(f"/api/photo-sessions/{session_id}/reload", headers=headers)
    assert reloaded.status_code == 200
    process_job(started.json()["id"])
    session = client.get(f"/api/photo-sessions/{session_id}", headers=headers).json()
    job = client.get(f"/api/jobs/{started.json()['id']}", headers=headers).json()
    assert job["status"] == "succeeded"
    assert job["applied_to_active"] is False
    assert session["active_version_id"] == session["root_version_id"]
    assert session["unseen_result_version_id"] == job["result_version_id"]
    saved = next(version for version in session["versions"] if version["id"] == job["result_version_id"])
    assert saved["parent_version_id"] == session["root_version_id"]


def test_idempotency_and_duplicate_submission(client):
    headers = auth(client)
    session_id, frame = session_with_items(client, headers)
    hat = item_by_prompt(frame, "hat")
    first = try_on(client, headers, session_id, hat, "idem-same-key1")
    second = try_on(client, headers, session_id, hat, "idem-same-key1")
    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["id"] == second.json()["id"]
    third = try_on(client, headers, session_id, hat, "idem-other-key")
    assert third.status_code == 409
    assert third.json()["error"]["code"] == "job_in_progress"
    process_job(first.json()["id"])


def test_failed_job_preserves_active_version(client):
    headers = auth(client)
    session_id, frame = session_with_items(client, headers)
    before = client.get(f"/api/photo-sessions/{session_id}", headers=headers).json()
    hat = item_by_prompt(frame, "hat")
    started = try_on(client, headers, session_id, hat, "idem-fail-00001", demo_fail=True)
    job = finish(client, headers, started)
    assert job["status"] == "failed"
    assert job["retryable"] is True
    after = client.get(f"/api/photo-sessions/{session_id}", headers=headers).json()
    assert after["active_version_id"] == before["active_version_id"]
    assert len(after["versions"]) == len(before["versions"])
    retry = finish(client, headers, try_on(client, headers, session_id, hat, "idem-retry-0001"))
    assert retry["status"] == "succeeded"
    final = client.get(f"/api/photo-sessions/{session_id}", headers=headers).json()
    assert len(final["versions"]) == 2


def test_deletion_keeps_unrelated_branches_and_referenced_assets(client):
    headers = auth(client)
    session_id, frame = session_with_items(client, headers)
    hat = item_by_prompt(frame, "hat")
    jacket = item_by_prompt(frame, "jacket")
    shoe = item_by_prompt(frame, "shoe")
    finish(client, headers, try_on(client, headers, session_id, hat, "idem-del-hat01"))
    current = client.get(f"/api/photo-sessions/{session_id}", headers=headers).json()
    hat_version = next(version for version in current["versions"] if version["category"] == "hat")
    finish(client, headers, try_on(client, headers, session_id, jacket, "idem-del-jack1"))
    client.post(f"/api/photo-sessions/{session_id}/active", headers=headers, json={"version_id": hat_version["id"]})
    finish(client, headers, try_on(client, headers, session_id, shoe, "idem-del-shoe1"))
    full = client.get(f"/api/photo-sessions/{session_id}", headers=headers).json()
    jacket_version = next(version for version in full["versions"] if version["category"] == "outerwear")
    shoes_version = next(version for version in full["versions"] if version["category"] == "shoes")
    blocked = client.delete(f"/api/versions/{hat_version['id']}", headers=headers)
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "has_descendants"
    removed = client.delete(f"/api/versions/{shoes_version['id']}", headers=headers)
    assert removed.status_code == 200
    remaining = {version["id"] for version in removed.json()["versions"]}
    assert shoes_version["id"] not in remaining
    assert jacket_version["id"] in remaining
    assert hat_version["id"] in remaining
    db = SessionLocal()
    try:
        assert db.get(Asset, shoes_version["asset_id"]) is None
        assert db.get(Asset, full["original_asset_id"]) is not None
    finally:
        db.close()
    rooted = client.delete(f"/api/versions/{full['root_version_id']}", headers=headers)
    assert rooted.status_code == 400


def test_search_missing_fields_and_non_product_links(client):
    headers = auth(client)
    _session_id, frame = session_with_items(client, headers)
    hat = item_by_prompt(frame, "hat")
    found = client.post(f"/api/items/{hat['id']}/search", headers=headers)
    assert found.status_code == 200, found.text
    body = found.json()
    assert body["demo_data"] is True
    prices = [item["price"] for item in body["results"]]
    assert None in prices
    assert any(item["result_type"] == "similar_style" for item in body["results"])
    assert all(item["url"].startswith("https://") for item in body["results"])
    similar = next(item for item in body["results"] if item["result_type"] == "similar_style")
    assert similar["price"] is None
    assert similar["image"] is None


def test_session_ownership(client):
    owner = auth(client)
    other = auth(client)
    session_id, _frame = session_with_items(client, owner)
    hidden = client.get(f"/api/photo-sessions/{session_id}", headers=other)
    assert hidden.status_code == 404
    listed = client.get("/api/photo-sessions", headers=other)
    assert listed.json()["sessions"] == []


def test_real_mode_never_substitutes_demo_results(client, monkeypatch):
    headers = auth(client)
    session_id, frame = session_with_items(client, headers)
    hat = item_by_prompt(frame, "hat")
    monkeypatch.setenv("FRAMEFIT_MODE", "real")
    monkeypatch.setenv("YOUCAM_API_KEY", "")
    get_settings.cache_clear()
    try:
        blocked = try_on(client, headers, session_id, hat, "idem-real-00001")
        assert blocked.status_code == 503
        before = client.get(f"/api/photo-sessions/{session_id}", headers=headers).json()
        monkeypatch.setenv("YOUCAM_API_KEY", "present")
        get_settings.cache_clear()

        def explode(*_args, **_kwargs):
            raise ProviderError("The try-on service could not finish this image.", retryable=True)

        monkeypatch.setattr("app.domain.run_youcam", explode)
        started = try_on(client, headers, session_id, hat, "idem-real-00002")
        job = finish(client, headers, started)
        assert job["status"] == "failed"
        assert job["provider"] == "youcam"
        after = client.get(f"/api/photo-sessions/{session_id}", headers=headers).json()
        assert len(after["versions"]) == len(before["versions"])
    finally:
        monkeypatch.setenv("FRAMEFIT_MODE", "demo")
        monkeypatch.setenv("YOUCAM_API_KEY", "")
        get_settings.cache_clear()


def test_manual_item_and_invalid_image(client):
    headers = auth(client)
    session_id, frame = session_with_items(client, headers)
    created = client.post(
        f"/api/inspiration-frames/{frame['id']}/items",
        headers=headers,
        json={"category": "scarf", "x": 0.2, "y": 0.2, "width": 0.3, "height": 0.2},
    )
    assert created.status_code == 201
    assert any(item["category_prompt"] == "scarf" and item["manual"] for item in created.json()["items"])
    rejected = client.post("/api/photo-sessions", headers=headers, files={"file": ("notes.txt", b"hello", "text/plain")})
    assert rejected.status_code == 400
    assert session_id


def test_video_link_rejects_private_addresses_and_returns_a_playable_file(client, monkeypatch):
    headers = auth(client)
    blocked = client.post("/api/video-source", headers=headers, json={"url": "http://127.0.0.1/secret.mp4"})
    assert blocked.status_code == 400

    monkeypatch.setattr("app.providers.video_source.download_video", lambda _url: (b"\x00\x00\x00\x18ftypmp42" + b"x" * 1200, "video/mp4"))
    opened = client.post("/api/video-source", headers=headers, json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"})
    assert opened.status_code == 200
    assert opened.headers["content-type"].startswith("video/mp4")
    assert opened.content.startswith(b"\x00\x00\x00\x18ftyp")
