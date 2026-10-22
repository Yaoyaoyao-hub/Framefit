import io

import httpx
import pytest
from PIL import Image

from app.providers.search import normalize_visual_matches
from app.providers.youcam import YouCamClient, build_task_payload
from app.ssrf import assert_public_url
from app.errors import ProviderError


def jpeg() -> bytes:
    image = Image.new("RGB", (640, 800), (20, 40, 60))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG")
    return buffer.getvalue()


def test_search_normalization_preserves_missing_fields_and_labels_non_products():
    matches = [
        {
            "title": "Shop page",
            "link": "https://shop.example.com/products/coat?utm_source=ad",
            "source": "Shop",
            "price": {"extracted_value": 80, "currency": "$"},
            "image": "https://images.example.com/coat.jpg",
            "exact_matches": True,
        },
        {
            "title": "Shop page duplicate",
            "link": "https://shop.example.com/products/coat",
            "source": "Shop",
            "price": {"extracted_value": 80, "currency": "$"},
        },
        {
            "title": "Forum thread",
            "link": "https://www.reddit.com/r/fashion/comments/abc",
            "source": "Reddit",
        },
        {
            "title": "No price product path",
            "link": "https://merchant.example.com/item/123",
            "source": "Merchant",
            "image": "not-a-url",
        },
        {"title": "Bad", "link": "javascript:alert(1)"},
    ]
    results = normalize_visual_matches(matches)
    assert len(results) == 3
    assert results[0]["result_type"] == "product"
    assert results[0]["price"] == 80
    assert results[0]["exact_image_match"] is True
    forum = next(item for item in results if "reddit" in item["url"])
    assert forum["result_type"] == "similar_style"
    assert forum["price"] is None
    assert forum["currency"] is None
    missing_image = next(item for item in results if item["title"] == "No price product path")
    assert missing_image["image"] is None
    assert missing_image["price"] is None


def test_private_urls_are_rejected():
    with pytest.raises(ProviderError):
        assert_public_url("http://127.0.0.1/latest/meta-data")
    with pytest.raises(ProviderError):
        assert_public_url("http://169.254.169.254/latest/meta-data")
    with pytest.raises(ProviderError):
        assert_public_url("file:///etc/passwd")


def test_youcam_adapters_use_documented_payloads(monkeypatch):
    monkeypatch.setattr("app.providers.youcam.assert_public_url", lambda _url: None)
    monkeypatch.setattr("app.ssrf.assert_public_url", lambda _url: None)
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path, request.content))
        if request.url.path == "/s2s/v2.0/file":
            return httpx.Response(
                200,
                json={
                    "status": 200,
                    "data": {
                        "files": [
                            {
                                "file_id": f"file-{len(calls)}",
                                "requests": [
                                    {
                                        "method": "PUT",
                                        "url": "https://example.com/upload",
                                        "headers": {"Content-Type": "image/jpg", "Content-Length": "1"},
                                    }
                                ],
                            }
                        ]
                    },
                },
            )
        if request.method == "PUT":
            return httpx.Response(200)
        if request.url.path == "/s2s/v2.0/task/hat":
            return httpx.Response(200, json={"status": 200, "data": {"task_id": "hat-task"}})
        if request.url.path == "/s2s/v2.0/task/cloth-v4":
            return httpx.Response(200, json={"status": 200, "data": {"task_id": "cloth-task"}})
        if request.url.path == "/s2s/v2.0/task/shoes-transfer":
            return httpx.Response(200, json={"status": 200, "data": {"task_id": "shoe-task"}})
        if request.url.path.endswith("/hat-task"):
            return httpx.Response(200, json={"status": 200, "data": {"task_status": "success", "results": {"url": "https://example.com/result.jpg"}}})
        if request.url.path == "/result.jpg":
            return httpx.Response(200, content=jpeg(), headers={"content-type": "image/jpeg"})
        return httpx.Response(404)

    client = YouCamClient("secret-key", "https://yce-api-01.makeupar.com", transport=httpx.MockTransport(handler))
    from app.providers.youcam import run_youcam

    image, meta = run_youcam("hat", jpeg(), jpeg(), {"gender": "female", "style": "random", "input_mode": "file_upload"}, client=client)
    assert image[:2] == b"\xff\xd8"
    assert meta["endpoint"] == "/s2s/v2.0/task/hat"
    hat_call = next(call for call in calls if call[1] == "/s2s/v2.0/task/hat")
    body = hat_call[2].decode()
    assert "src_file_id" in body
    assert "ref_file_id" in body
    assert "female" in body
    assert "random" in body
    assert "secret-key" not in body

    path, payload = build_task_payload("outerwear", {"change_shoes": False, "filter_multi_person": "off"}, src_file_id="s", ref_file_id="r")
    assert path == "/s2s/v2.0/task/cloth-v4"
    assert payload["garment_category"] == "outer"
    assert payload["change_shoes"] is False
    assert "gender" not in payload

    shoes_path, shoes_payload = build_task_payload("shoes", {}, src_file_id="s", ref_file_id="r")
    assert shoes_path == "/s2s/v2.0/task/shoes-transfer"
    assert set(shoes_payload) == {"src_file_id", "ref_file_id"}

    scarf_path, scarf_payload = build_task_payload("scarf", {"gender": "male", "style": "style_bohemian"}, src_file_url="https://example.com/a.jpg", ref_file_url="https://example.com/b.jpg")
    assert scarf_path == "/s2s/v2.0/task/scarf"
    assert scarf_payload["style"] == "style_bohemian"
    assert "src_file_url" in scarf_payload

    hat_only_path, hat_only = build_task_payload("hat", {"gender": "female", "keep_outfit": True, "style": "style_sporty_casual"}, src_file_id="s", ref_file_id="r")
    assert hat_only_path == "/s2s/v2.0/task/hat"
    assert "style" not in hat_only
    assert hat_only["gender"] == "female"

    bag_path, bag_payload = build_task_payload("bag", {"gender": "female", "style": "style_parisian_chic"}, src_file_id="s", ref_file_id="r")
    assert bag_path == "/s2s/v2.0/task/bag"
    assert bag_payload["gender"] == "female"
    assert bag_payload["style"] == "style_parisian_chic"
    assert bag_payload["src_file_id"] == "s"
    assert "garment_category" not in bag_payload
