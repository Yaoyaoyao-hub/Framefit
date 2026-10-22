"""Photo sessions, versions, try-on jobs, and product search."""

from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.categories import ALLOWED_PROMPTS, internal_category, label_for
from app.config import get_settings
from app.errors import APIError, ProviderError
from app.images import (
    PreparedImage,
    crop_normalized,
    demo_composite,
    keep_original_outfit,
    open_image,
    prepare_upload,
    sample_inspiration,
    sample_person,
    sample_product,
)
from app.models import (
    Asset,
    DetectedItem,
    GenerationVersion,
    InspirationFrame,
    PhotoSession,
    TryOnJob,
    utcnow,
)
from app.providers.search import fetch_remote_image, search_visual_matches
from app.providers.youcam import BAG_STYLES, HAT_STYLES, SCARF_STYLES, adapter_name, run_youcam
from app.security import sign_asset, verify_asset_signature
from app.ssrf import is_safe_link
from app.storage import get_storage

mutation_lock = threading.Lock()

TERMINAL = {"succeeded", "failed", "interrupted"}


def new_id() -> str:
    return str(uuid.uuid4())


def workspace_storage_bytes(db: Session, workspace_id: str) -> int:
    value = db.query(func.coalesce(func.sum(Asset.byte_size), 0)).filter(Asset.workspace_id == workspace_id).scalar()
    return int(value or 0)


def store_prepared(db: Session, workspace_id: str, prepared: PreparedImage, kind: str) -> Asset:
    existing = db.query(Asset).filter_by(workspace_id=workspace_id, sha256=prepared.sha256).one_or_none()
    if existing:
        return existing
    settings = get_settings()
    if workspace_storage_bytes(db, workspace_id) + len(prepared.data) > settings.max_storage_bytes:
        raise APIError(
            409,
            "limit_reached",
            "Saved images have reached the storage limit. Delete a photo session or saved versions to free space.",
        )
    asset = Asset(
        id=new_id(),
        workspace_id=workspace_id,
        storage_key="",
        sha256=prepared.sha256,
        mime=prepared.mime,
        width=prepared.width,
        height=prepared.height,
        byte_size=len(prepared.data),
        kind=kind,
    )
    asset.storage_key = f"{workspace_id}/{asset.id}"
    get_storage().put(asset.storage_key, prepared.data, prepared.mime)
    db.add(asset)
    db.flush()
    return asset


def store_bytes(db: Session, workspace_id: str, data: bytes, kind: str) -> Asset:
    return store_prepared(db, workspace_id, prepare_upload(data), kind)


def read_asset(asset: Asset) -> bytes:
    return get_storage().get(asset.storage_key)


def asset_in_use(db: Session, asset_id: str, *, ignoring_versions: set[str] | None = None, ignoring_items: set[str] | None = None, ignoring_frames: set[str] | None = None) -> bool:
    if db.query(PhotoSession.id).filter(PhotoSession.original_asset_id == asset_id).first():
        return True
    version_query = db.query(GenerationVersion.id).filter(
        or_(GenerationVersion.asset_id == asset_id, GenerationVersion.reference_asset_id == asset_id)
    )
    if ignoring_versions:
        version_query = version_query.filter(~GenerationVersion.id.in_(ignoring_versions))
    if version_query.first():
        return True
    frame_query = db.query(InspirationFrame.id).filter(InspirationFrame.asset_id == asset_id)
    if ignoring_frames:
        frame_query = frame_query.filter(~InspirationFrame.id.in_(ignoring_frames))
    if frame_query.first():
        return True
    item_query = db.query(DetectedItem.id).filter(DetectedItem.crop_asset_id == asset_id)
    if ignoring_items:
        item_query = item_query.filter(~DetectedItem.id.in_(ignoring_items))
    if item_query.first():
        return True
    if db.query(TryOnJob.id).filter(TryOnJob.reference_asset_id == asset_id, ~TryOnJob.status.in_(TERMINAL)).first():
        return True
    return False


def purge_asset(db: Session, asset_id: str, **ignore) -> None:
    if asset_in_use(db, asset_id, **ignore):
        return
    asset = db.get(Asset, asset_id)
    if not asset:
        return
    try:
        get_storage().delete(asset.storage_key)
    except Exception:
        pass
    db.delete(asset)


def create_photo_session(db: Session, workspace_id: str, data: bytes) -> PhotoSession:
    asset = store_bytes(db, workspace_id, data, "original")
    session = PhotoSession(id=new_id(), workspace_id=workspace_id, original_asset_id=asset.id, revision=0)
    root = GenerationVersion(
        id=new_id(),
        session_id=session.id,
        parent_version_id=None,
        asset_id=asset.id,
        category=None,
        label="Original",
        settings_json="{}",
        origin="root",
        is_root=True,
    )
    session.root_version_id = root.id
    session.active_version_id = root.id
    db.add(session)
    db.add(root)
    db.commit()
    db.refresh(session)
    return session


def list_sessions(db: Session, workspace_id: str) -> list[PhotoSession]:
    return db.query(PhotoSession).filter_by(workspace_id=workspace_id).order_by(PhotoSession.created_at.desc()).all()


def get_session(db: Session, workspace_id: str, session_id: str) -> PhotoSession:
    session = db.get(PhotoSession, session_id)
    if not session or session.workspace_id != workspace_id:
        raise APIError(404, "not_found", "That photo could not be found.")
    return session


def get_version(db: Session, workspace_id: str, version_id: str) -> GenerationVersion:
    version = db.get(GenerationVersion, version_id)
    if not version:
        raise APIError(404, "not_found", "That saved version could not be found.")
    get_session(db, workspace_id, version.session_id)
    return version


def versions_for(db: Session, session_id: str) -> list[GenerationVersion]:
    return db.query(GenerationVersion).filter_by(session_id=session_id).order_by(GenerationVersion.created_at.asc()).all()


def set_active(db: Session, session: PhotoSession, version_id: str) -> PhotoSession:
    version = db.get(GenerationVersion, version_id)
    if not version or version.session_id != session.id:
        raise APIError(404, "not_found", "That saved version could not be found.")
    with mutation_lock:
        db.refresh(session)
        if session.active_version_id != version.id:
            session.active_version_id = version.id
            session.revision += 1
        db.commit()
    db.refresh(session)
    return session


def undo(db: Session, session: PhotoSession) -> PhotoSession:
    current = db.get(GenerationVersion, session.active_version_id)
    if not current or not current.parent_version_id:
        raise APIError(400, "nothing_to_undo", "This is already the original photo.")
    return set_active(db, session, current.parent_version_id)


def reset_look(db: Session, session: PhotoSession) -> PhotoSession:
    if not session.root_version_id:
        raise APIError(400, "nothing_to_reset", "This photo has no original to return to.")
    return set_active(db, session, session.root_version_id)


def reload_session(db: Session, session: PhotoSession) -> PhotoSession:
    with mutation_lock:
        db.refresh(session)
        session.active_version_id = session.root_version_id
        session.revision += 1
        db.commit()
    db.refresh(session)
    return session


def acknowledge_result(db: Session, session: PhotoSession) -> PhotoSession:
    session.unseen_result_version_id = None
    db.commit()
    db.refresh(session)
    return session


def create_frame(db: Session, workspace_id: str, session_id: str, data: bytes, source_kind: str, source_url: str | None) -> InspirationFrame:
    get_session(db, workspace_id, session_id)
    if source_kind not in {"upload", "video_frame", "tab_capture"}:
        raise APIError(400, "invalid_source", "Choose an image, a video frame, or a shared tab.")
    asset = store_bytes(db, workspace_id, data, "inspiration")
    frame = InspirationFrame(
        id=new_id(),
        workspace_id=workspace_id,
        session_id=session_id,
        asset_id=asset.id,
        source_url=source_url,
        source_kind=source_kind,
    )
    db.add(frame)
    db.commit()
    db.refresh(frame)
    return frame


def get_frame(db: Session, workspace_id: str, frame_id: str) -> InspirationFrame:
    frame = db.get(InspirationFrame, frame_id)
    if not frame or frame.workspace_id != workspace_id:
        raise APIError(404, "not_found", "That inspiration image could not be found.")
    return frame


def _save_item(db: Session, frame: InspirationFrame, prompt: str, confidence: float | None, x: float, y: float, width: float, height: float, manual: bool) -> DetectedItem:
    _validate_box(x, y, width, height)
    category = internal_category(prompt)
    source = db.get(Asset, frame.asset_id)
    crop = crop_normalized(read_asset(source), x, y, width, height)
    crop_asset = store_prepared(db, frame.workspace_id, crop, "crop")
    item = DetectedItem(
        id=new_id(),
        frame_id=frame.id,
        workspace_id=frame.workspace_id,
        category_prompt=prompt.strip().lower(),
        internal_category=category,
        confidence=confidence,
        x=x,
        y=y,
        width=width,
        height=height,
        crop_asset_id=crop_asset.id,
        manual=manual,
    )
    db.add(item)
    db.flush()
    return item


def detect_frame(db: Session, frame: InspirationFrame) -> list[DetectedItem]:
    from app.detection import detect

    asset = db.get(Asset, frame.asset_id)
    data = read_asset(asset)
    image = open_image(data)
    found = detect(data, image.size[0], image.size[1])
    existing = db.query(DetectedItem).filter_by(frame_id=frame.id, manual=False).all()
    removed_ids = {item.id for item in existing}
    removed_crops = [item.crop_asset_id for item in existing if item.crop_asset_id]
    for item in existing:
        db.delete(item)
    db.flush()
    created = []
    for entry in found:
        created.append(
            _save_item(
                db,
                frame,
                entry["category_prompt"],
                entry.get("confidence"),
                entry["x"],
                entry["y"],
                entry["width"],
                entry["height"],
                False,
            )
        )
    db.flush()
    kept = {item.crop_asset_id for item in created if item.crop_asset_id}
    for crop_id in removed_crops:
        if crop_id not in kept:
            purge_asset(db, crop_id, ignoring_items=removed_ids)
    db.commit()
    return db.query(DetectedItem).filter_by(frame_id=frame.id).order_by(DetectedItem.created_at.asc()).all()


def create_manual_item(db: Session, frame: InspirationFrame, prompt: str, x: float, y: float, width: float, height: float) -> DetectedItem:
    if prompt.strip().lower() not in ALLOWED_PROMPTS:
        raise APIError(400, "invalid_category", "Choose one of the listed clothing categories.")
    item = _save_item(db, frame, prompt, None, x, y, width, height, True)
    db.commit()
    db.refresh(item)
    return item


def update_item(db: Session, workspace_id: str, item_id: str, *, prompt: str | None, box: tuple[float, float, float, float] | None) -> DetectedItem:
    item = _get_item(db, workspace_id, item_id)
    frame = db.get(InspirationFrame, item.frame_id)
    if prompt:
        if prompt.strip().lower() not in ALLOWED_PROMPTS:
            raise APIError(400, "invalid_category", "Choose one of the listed clothing categories.")
        item.category_prompt = prompt.strip().lower()
        item.internal_category = internal_category(item.category_prompt)
    if box:
        _validate_box(*box)
        item.x, item.y, item.width, item.height = box
    if prompt or box:
        source = db.get(Asset, frame.asset_id)
        previous = item.crop_asset_id
        crop = crop_normalized(read_asset(source), item.x, item.y, item.width, item.height)
        item.crop_asset_id = store_prepared(db, workspace_id, crop, "crop").id
        db.flush()
        if previous:
            purge_asset(db, previous)
    db.commit()
    db.refresh(item)
    return item


def _get_item(db: Session, workspace_id: str, item_id: str) -> DetectedItem:
    item = db.get(DetectedItem, item_id)
    if not item or item.workspace_id != workspace_id:
        raise APIError(404, "not_found", "That item could not be found.")
    return item


def _validate_box(x: float, y: float, width: float, height: float) -> None:
    if width <= 0.01 or height <= 0.01 or x < 0 or y < 0 or x + width > 1.02 or y + height > 1.02:
        raise APIError(400, "invalid_box", "Draw the box inside the inspiration image.")


def create_try_on(db: Session, workspace_id: str, session_id: str, payload: dict) -> TryOnJob:
    settings = get_settings()
    session = get_session(db, workspace_id, session_id)
    key = str(payload.get("idempotency_key") or "").strip()
    if len(key) < 8 or len(key) > 80:
        raise APIError(400, "invalid_request", "Try that again.")
    with mutation_lock:
        db.refresh(session)
        existing = db.query(TryOnJob).filter_by(session_id=session.id, idempotency_key=key).one_or_none()
        if existing:
            return existing
        if payload.get("expected_revision") != session.revision:
            raise APIError(409, "stale_revision", "The photo changed before this try-on started. Look at the current version and try again.")
        if session.active_job_id:
            active = db.get(TryOnJob, session.active_job_id)
            if active and active.status not in TERMINAL:
                raise APIError(409, "job_in_progress", "A try-on is already running for this photo.")
        generated = db.query(GenerationVersion).filter_by(session_id=session.id, is_root=False).count()
        if generated >= settings.max_generations_per_session:
            raise APIError(
                409,
                "limit_reached",
                "This photo has reached the saved try-on limit. Delete some saved versions to continue.",
            )
        origin = payload.get("origin")
        if origin not in {"inspiration", "product"}:
            raise APIError(400, "invalid_request", "Choose an inspiration item or a product.")
        reference_asset_id, category, frame_id, item_id, product_snapshot = _resolve_reference(db, workspace_id, session, payload)
        _ensure_try_on_available(category)
        options = _job_settings(category, payload)
        if payload.get("demo_fail") and settings.mode == "real":
            raise APIError(400, "invalid_request", "That option is only available in demo mode.")
        job = TryOnJob(
            id=new_id(),
            workspace_id=workspace_id,
            session_id=session.id,
            idempotency_key=key,
            expected_revision=session.revision,
            source_version_id=session.active_version_id,
            status="queued",
            origin=origin,
            internal_category=category,
            reference_asset_id=reference_asset_id,
            frame_id=frame_id,
            item_id=item_id,
            product_snapshot_json=json.dumps(product_snapshot) if product_snapshot else None,
            settings_json=json.dumps(options),
            provider="youcam" if _live_try_on() else "demo",
        )
        session.active_job_id = job.id
        db.add(job)
        db.commit()
        db.refresh(job)
        return job


def _live_try_on() -> bool:
    settings = get_settings()
    return settings.mode in {"mixed", "real"} and settings.youcam_configured


def _ensure_try_on_available(category: str) -> None:
    settings = get_settings()
    adapter_name(category)
    if settings.mode == "real" and not settings.youcam_configured:
        raise APIError(503, "unavailable", "Try-on is unavailable until it is configured.")


def _job_settings(category: str, payload: dict) -> dict:
    settings = get_settings()
    name = adapter_name(category)
    options = {
        "reference_kind": payload.get("reference_kind") or settings.youcam_reference_kind,
        "input_mode": settings.youcam_input_mode,
        "change_shoes": bool(payload.get("change_shoes", False)),
        "filter_multi_person": payload.get("filter_multi_person") or "off",
        "demo_fail": bool(payload.get("demo_fail", False)),
    }
    if name in {"hat", "scarf", "bag"}:
        gender = payload.get("gender")
        if gender not in {"female", "male"}:
            raise APIError(400, "gender_required", "Choose female or male for this try-on.")
        style = payload.get("style") or "random"
        allowed = {"hat": HAT_STYLES, "scarf": SCARF_STYLES, "bag": BAG_STYLES}[name]
        if style not in allowed:
            raise APIError(400, "invalid_style", "That style option is not supported for this item.")
        options["gender"] = gender
        options["style"] = style
    if name == "hat":
        options["keep_outfit"] = payload.get("keep_outfit", True) is not False
    if options["filter_multi_person"] not in {"off", "normal", "strict"}:
        raise APIError(400, "invalid_request", "Choose how extra people in the photo should be handled.")
    if options["reference_kind"] not in {"crop", "frame", "product"}:
        raise APIError(400, "invalid_request", "Choose a crop or the full inspiration image.")
    return options


def _resolve_reference(db: Session, workspace_id: str, session: PhotoSession, payload: dict) -> tuple[str, str, str | None, str | None, dict | None]:
    settings = get_settings()
    if payload.get("origin") == "inspiration":
        item = _get_item(db, workspace_id, payload.get("item_id") or "")
        frame = get_frame(db, workspace_id, item.frame_id)
        if frame.session_id != session.id:
            raise APIError(400, "invalid_request", "That item belongs to a different photo.")
        kind = payload.get("reference_kind") or settings.youcam_reference_kind
        if kind == "frame":
            return frame.asset_id, item.internal_category, frame.id, item.id, None
        if not item.crop_asset_id:
            raise APIError(400, "invalid_request", "That item does not have an image crop yet.")
        return item.crop_asset_id, item.internal_category, frame.id, item.id, None
    product = payload.get("product") or {}
    item_id = payload.get("item_id")
    if item_id:
        item = _get_item(db, workspace_id, item_id)
        category = item.internal_category
        frame_id = item.frame_id
    else:
        prompt = payload.get("category") or ""
        category = internal_category(prompt)
        frame_id = None
        item_id = None
    url = product.get("url")
    if not is_safe_link(url):
        raise APIError(400, "invalid_link", "That product link cannot be opened.")
    image_url = product.get("image")
    if not image_url:
        raise APIError(400, "missing_image", "This result does not include an image to try on.")
    image_bytes = _load_product_image(db, workspace_id, image_url)
    asset = store_bytes(db, workspace_id, image_bytes, "product")
    snapshot = {
        "title": str(product.get("title") or "Untitled result"),
        "source": product.get("source"),
        "url": url,
        "price": product.get("price"),
        "currency": product.get("currency"),
        "result_type": product.get("result_type") if product.get("result_type") in {"product", "similar_style"} else "similar_style",
        "image_asset_id": asset.id,
    }
    return asset.id, category, frame_id, item_id, snapshot


def _load_product_image(db: Session, workspace_id: str, image_url: str) -> bytes:
    parsed = urlparse(image_url)
    path = parsed.path
    if path.startswith("/api/assets/") and path.endswith("/content"):
        asset_id = path.split("/")[3]
        query = parse_qs(parsed.query)
        exp = (query.get("exp") or [""])[0]
        sig = (query.get("sig") or [""])[0]
        verify_asset_signature(asset_id, exp, sig)
        asset = db.get(Asset, asset_id)
        if not asset or asset.workspace_id != workspace_id:
            raise APIError(404, "not_found", "That product image could not be found.")
        return read_asset(asset)
    if not is_safe_link(image_url):
        raise APIError(400, "invalid_link", "That product image cannot be used.")
    try:
        return fetch_remote_image(image_url)
    except ProviderError as exc:
        raise APIError(400, "invalid_image", exc.message) from exc


def get_job(db: Session, workspace_id: str, job_id: str) -> TryOnJob:
    job = db.get(TryOnJob, job_id)
    if not job or job.workspace_id != workspace_id:
        raise APIError(404, "not_found", "That try-on could not be found.")
    return job


def process_job(job_id: str, *, resume: bool = False) -> None:
    from app.db import SessionLocal

    db = SessionLocal()
    try:
        with mutation_lock:
            job = db.get(TryOnJob, job_id)
            if not job or job.status in TERMINAL:
                return
            if job.status == "running" and not resume:
                return
            job.status = "running"
            job.updated_at = utcnow()
            db.commit()
        try:
            result, meta = _run_provider(db, job)
            prepared = prepare_upload(result)
            _commit_success(db, job.id, prepared, meta)
        except ProviderError as exc:
            _commit_failure(db, job.id, exc.message, exc.retryable)
        except APIError as exc:
            _commit_failure(db, job.id, exc.message, False)
        except Exception:
            _commit_failure(db, job.id, "The try-on could not be saved. You can try again.", True)
    finally:
        db.close()


def _run_provider(db: Session, job: TryOnJob) -> tuple[bytes, dict]:
    settings = get_settings()
    options = json.loads(job.settings_json or "{}")
    if options.get("demo_fail"):
        raise ProviderError("The demo try-on failed before saving a result.", retryable=True)
    source_version = db.get(GenerationVersion, job.source_version_id)
    source_asset = db.get(Asset, source_version.asset_id)
    reference_asset = db.get(Asset, job.reference_asset_id)
    source = read_asset(source_asset)
    reference = read_asset(reference_asset)
    if _live_try_on():
        image, meta = run_youcam(job.internal_category, source, reference, options)
        if job.internal_category == "hat" and options.get("keep_outfit", True):
            image, placement = keep_original_outfit(source, image)
            meta["placement"] = placement
        return image, meta
    image = demo_composite(source, reference, job.internal_category, job.origin)
    return image, {"provider": "demo", "provider_task_id": None, "endpoint": None}


def _commit_success(db: Session, job_id: str, prepared: PreparedImage, meta: dict) -> None:
    with mutation_lock:
        job = db.get(TryOnJob, job_id)
        if not job or job.status in TERMINAL:
            return
        session = db.get(PhotoSession, job.session_id)
        asset = store_prepared(db, job.workspace_id, prepared, "result")
        version = GenerationVersion(
            id=new_id(),
            session_id=job.session_id,
            parent_version_id=job.source_version_id,
            asset_id=asset.id,
            category=job.internal_category,
            label=label_for(job.internal_category, origin=job.origin),
            inspiration_frame_id=job.frame_id,
            detected_item_id=job.item_id,
            product_snapshot_json=job.product_snapshot_json,
            reference_asset_id=job.reference_asset_id,
            settings_json=job.settings_json,
            provider=meta.get("provider"),
            provider_task_id=meta.get("provider_task_id"),
            app_job_id=job.id,
            origin=job.origin,
            is_root=False,
        )
        db.add(version)
        apply = session.active_version_id == job.source_version_id and session.revision == job.expected_revision and session.active_job_id == job.id
        if apply:
            session.active_version_id = version.id
            session.revision += 1
            job.applied_to_active = True
        else:
            job.applied_to_active = False
            session.unseen_result_version_id = version.id
        if session.active_job_id == job.id:
            session.active_job_id = None
        job.status = "succeeded"
        job.result_version_id = version.id
        job.provider = meta.get("provider")
        job.provider_task_id = meta.get("provider_task_id")
        job.updated_at = utcnow()
        job.error_message = None
        db.commit()


def mark_interrupted(job_id: str) -> None:
    from app.db import SessionLocal

    db = SessionLocal()
    try:
        _commit_terminal(db, job_id, "interrupted", "This try-on was interrupted. You can try again.", True)
    finally:
        db.close()


def _commit_failure(db: Session, job_id: str, message: str, retryable: bool) -> None:
    _commit_terminal(db, job_id, "failed", message, retryable)


def _commit_terminal(db: Session, job_id: str, status: str, message: str, retryable: bool) -> None:
    with mutation_lock:
        job = db.get(TryOnJob, job_id)
        if not job or job.status in TERMINAL:
            return
        session = db.get(PhotoSession, job.session_id)
        job.status = status
        job.error_message = message
        job.retryable = retryable
        job.updated_at = utcnow()
        if session and session.active_job_id == job.id:
            session.active_job_id = None
        db.commit()


def descendants(versions: list[GenerationVersion], version_id: str) -> list[GenerationVersion]:
    children: dict[str | None, list[GenerationVersion]] = {}
    for version in versions:
        children.setdefault(version.parent_version_id, []).append(version)
    found: list[GenerationVersion] = []
    stack = [version_id]
    while stack:
        current = stack.pop()
        for child in children.get(current, []):
            found.append(child)
            stack.append(child.id)
    return found


def delete_version(db: Session, workspace_id: str, version_id: str, subtree: bool) -> PhotoSession:
    version = get_version(db, workspace_id, version_id)
    if version.is_root:
        raise APIError(400, "protected", "The original photo stays until you delete the whole photo session.")
    session = get_session(db, workspace_id, version.session_id)
    running = db.query(TryOnJob).filter(TryOnJob.session_id == session.id, ~TryOnJob.status.in_(TERMINAL), TryOnJob.source_version_id == version.id).first()
    if running:
        raise APIError(409, "job_in_progress", "A try-on is still using this version. Wait for it to finish, then delete it.")
    all_versions = versions_for(db, session.id)
    kids = descendants(all_versions, version.id)
    if kids and not subtree:
        raise APIError(
            409,
            "has_descendants",
            f"This version has {len(kids)} later saved version{'s' if len(kids) != 1 else ''}. Delete those too, or cancel.",
        )
    removing = [version, *kids] if subtree else [version]
    removing_ids = {item.id for item in removing}
    if any(job for job in db.query(TryOnJob).filter(TryOnJob.session_id == session.id, ~TryOnJob.status.in_(TERMINAL)).all() if job.source_version_id in removing_ids):
        raise APIError(409, "job_in_progress", "A try-on is still using one of these versions. Wait for it to finish, then delete.")
    asset_ids = []
    with mutation_lock:
        for item in removing:
            asset_ids.append(item.asset_id)
            if item.reference_asset_id:
                asset_ids.append(item.reference_asset_id)
            db.delete(item)
        db.flush()
        if session.active_version_id in removing_ids:
            session.active_version_id = version.parent_version_id or session.root_version_id
            session.revision += 1
        if session.unseen_result_version_id in removing_ids:
            session.unseen_result_version_id = None
        for asset_id in asset_ids:
            purge_asset(db, asset_id, ignoring_versions=removing_ids)
        db.commit()
    db.refresh(session)
    return session


def delete_session(db: Session, workspace_id: str, session_id: str) -> None:
    session = get_session(db, workspace_id, session_id)
    running = db.query(TryOnJob).filter(TryOnJob.session_id == session.id, ~TryOnJob.status.in_(TERMINAL)).first()
    if running:
        raise APIError(409, "job_in_progress", "A try-on is still running for this photo. Wait for it to finish, then delete the session.")
    frames = db.query(InspirationFrame).filter_by(session_id=session.id).all()
    frame_ids = [frame.id for frame in frames]
    items = db.query(DetectedItem).filter(DetectedItem.frame_id.in_(frame_ids)).all() if frame_ids else []
    versions = versions_for(db, session.id)
    jobs = db.query(TryOnJob).filter_by(session_id=session.id).all()
    asset_ids = {session.original_asset_id}
    for version in versions:
        asset_ids.add(version.asset_id)
        if version.reference_asset_id:
            asset_ids.add(version.reference_asset_id)
    for frame in frames:
        asset_ids.add(frame.asset_id)
    for item in items:
        if item.crop_asset_id:
            asset_ids.add(item.crop_asset_id)
    for job in jobs:
        asset_ids.add(job.reference_asset_id)
    version_ids = {version.id for version in versions}
    item_ids = {item.id for item in items}
    frame_id_set = set(frame_ids)
    for item in items:
        db.delete(item)
    for frame in frames:
        db.delete(frame)
    for job in jobs:
        db.delete(job)
    for version in versions:
        db.delete(version)
    db.delete(session)
    db.flush()
    for asset_id in asset_ids:
        if asset_id:
            purge_asset(db, asset_id, ignoring_versions=version_ids, ignoring_items=item_ids, ignoring_frames=frame_id_set)
    db.commit()


def search_item(db: Session, workspace_id: str, item_id: str) -> dict:
    item = _get_item(db, workspace_id, item_id)
    if not item.crop_asset_id:
        raise APIError(400, "invalid_request", "That item does not have an image to search.")
    crop = read_asset(db.get(Asset, item.crop_asset_id))
    settings = get_settings()
    source = "fixture"
    if settings.mode == "real":
        if not settings.serpapi_configured:
            raise APIError(503, "unavailable", "Product search is unavailable until it is configured.")
        try:
            results = search_visual_matches(crop, item.category_prompt.replace("_", " "))
            source = "serpapi"
        except ProviderError as exc:
            raise APIError(502, "search_failed", exc.message) from exc
    elif settings.mode == "mixed" and settings.serpapi_configured:
        try:
            results = search_visual_matches(crop, item.category_prompt.replace("_", " "))
            source = "serpapi"
        except ProviderError as exc:
            raise APIError(502, "search_failed", exc.message) from exc
    else:
        results = demo_search_results(db, workspace_id, item.internal_category)
    return {"source": source, "demo_data": source == "fixture", "item_id": item.id, "results": results}


def demo_search_results(db: Session, workspace_id: str, category: str) -> list[dict]:
    label = label_for(category)
    product_asset = store_bytes(db, workspace_id, sample_product(category), "product")
    db.commit()
    return [
        {
            "title": f"Sample {label.lower()} to compare",
            "source": "Sample merchant",
            "image": sign_asset(product_asset.id),
            "thumbnail": sign_asset(product_asset.id),
            "url": "https://example.com/products/framefit-sample",
            "price": 128.0,
            "currency": "$",
            "result_type": "product",
            "in_stock": None,
            "exact_image_match": None,
        },
        {
            "title": f"A {label.lower()} with no listed price",
            "source": "Sample shop",
            "image": sign_asset(product_asset.id),
            "thumbnail": sign_asset(product_asset.id),
            "url": "https://example.com/shop/unpriced-item",
            "price": None,
            "currency": None,
            "result_type": "product",
            "in_stock": None,
            "exact_image_match": None,
        },
        {
            "title": "Editorial mention of a similar style",
            "source": "Lookbook",
            "image": None,
            "thumbnail": None,
            "url": "https://example.com/stories/similar-style",
            "price": None,
            "currency": None,
            "result_type": "similar_style",
            "in_stock": None,
            "exact_image_match": None,
        },
    ]


def sample_bytes(kind: str) -> bytes:
    if kind == "person":
        return sample_person()
    if kind == "inspiration":
        return sample_inspiration()
    raise APIError(404, "not_found", "That sample is not available.")


def serialize_asset_url(asset_id: str | None) -> str | None:
    if not asset_id:
        return None
    return sign_asset(asset_id)


def serialize_version(version: GenerationVersion) -> dict:
    return {
        "id": version.id,
        "session_id": version.session_id,
        "parent_version_id": version.parent_version_id,
        "asset_id": version.asset_id,
        "image_url": sign_asset(version.asset_id),
        "created_at": _iso(version.created_at),
        "category": version.category,
        "label": version.label,
        "inspiration_frame_id": version.inspiration_frame_id,
        "detected_item_id": version.detected_item_id,
        "product": json.loads(version.product_snapshot_json) if version.product_snapshot_json else None,
        "reference_asset_id": version.reference_asset_id,
        "reference_image_url": serialize_asset_url(version.reference_asset_id),
        "settings": json.loads(version.settings_json or "{}"),
        "provider": version.provider,
        "provider_task_id": version.provider_task_id,
        "app_job_id": version.app_job_id,
        "origin": version.origin,
        "is_root": version.is_root,
    }


def serialize_job(job: TryOnJob) -> dict:
    return {
        "id": job.id,
        "session_id": job.session_id,
        "status": job.status,
        "origin": job.origin,
        "category": job.internal_category,
        "source_version_id": job.source_version_id,
        "result_version_id": job.result_version_id,
        "applied_to_active": job.applied_to_active,
        "error_message": job.error_message,
        "retryable": job.retryable,
        "provider": job.provider,
        "created_at": _iso(job.created_at),
        "updated_at": _iso(job.updated_at),
    }


def serialize_item(item: DetectedItem) -> dict:
    return {
        "id": item.id,
        "frame_id": item.frame_id,
        "category_prompt": item.category_prompt,
        "category": item.internal_category,
        "label": label_for(item.internal_category),
        "confidence": item.confidence,
        "x": item.x,
        "y": item.y,
        "width": item.width,
        "height": item.height,
        "crop_url": serialize_asset_url(item.crop_asset_id),
        "manual": item.manual,
    }


def serialize_frame(db: Session, frame: InspirationFrame) -> dict:
    asset = db.get(Asset, frame.asset_id)
    items = db.query(DetectedItem).filter_by(frame_id=frame.id).order_by(DetectedItem.created_at.asc()).all()
    return {
        "id": frame.id,
        "session_id": frame.session_id,
        "image_url": sign_asset(frame.asset_id),
        "width": asset.width if asset else None,
        "height": asset.height if asset else None,
        "source_url": frame.source_url,
        "source_kind": frame.source_kind,
        "created_at": _iso(frame.created_at),
        "items": [serialize_item(item) for item in items],
    }


def serialize_session(db: Session, session: PhotoSession, *, include_versions: bool = True) -> dict:
    original = db.get(Asset, session.original_asset_id)
    payload = {
        "id": session.id,
        "created_at": _iso(session.created_at),
        "revision": session.revision,
        "original_asset_id": session.original_asset_id,
        "image_url": sign_asset(session.original_asset_id),
        "width": original.width if original else None,
        "height": original.height if original else None,
        "root_version_id": session.root_version_id,
        "active_version_id": session.active_version_id,
        "active_job_id": session.active_job_id,
        "unseen_result_version_id": session.unseen_result_version_id,
    }
    if include_versions:
        payload["versions"] = [serialize_version(version) for version in versions_for(db, session.id)]
        frames = (
            db.query(InspirationFrame)
            .filter_by(session_id=session.id)
            .order_by(InspirationFrame.created_at.desc())
            .all()
        )
        payload["frames"] = [serialize_frame(db, frame) for frame in frames]
    return payload


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def public_capabilities() -> dict:
    from app.detection import detection_status

    settings = get_settings()
    detection = detection_status()
    if settings.mode == "demo":
        try_on = {"available": True, "source": "fixture", "reason": None}
        search = {"available": True, "source": "fixture", "reason": None}
    elif settings.mode == "mixed":
        if settings.youcam_configured:
            try_on = {"available": True, "source": "youcam", "reason": None}
        else:
            try_on = {"available": True, "source": "fixture", "reason": None}
        if settings.serpapi_configured:
            search = {"available": True, "source": "serpapi", "reason": None}
        else:
            search = {"available": True, "source": "fixture", "reason": None}
    else:
        try_on = {
            "available": settings.youcam_configured,
            "source": "youcam" if settings.youcam_configured else "unavailable",
            "reason": None if settings.youcam_configured else "Try-on is unavailable until it is configured.",
        }
        search = {
            "available": settings.serpapi_configured,
            "source": "serpapi" if settings.serpapi_configured else "unavailable",
            "reason": None if settings.serpapi_configured else "Product search is unavailable until it is configured.",
        }
    demo_data = any(item.get("source") == "fixture" for item in (detection, try_on, search))
    disclosure = []
    if settings.mode == "demo":
        disclosure.append("Detection, try-on, and product search are using demo data.")
    elif settings.mode == "mixed":
        if detection.get("source") == "yolo":
            disclosure.append("Detection is using the live model.")
        elif detection.get("source") == "fixture":
            disclosure.append("Detection is using sample boxes.")
        if try_on["source"] == "youcam":
            disclosure.append("Try-on uses the live hat, clothes, shoes, scarf, and bag APIs.")
        else:
            disclosure.append("Try-on uses demo images in this setup.")
        if search["source"] == "serpapi":
            disclosure.append("Product search uses live results.")
        else:
            disclosure.append("Product search uses demo results.")
    elif detection.get("source") == "fixture":
        disclosure.append(detection.get("detail") or "Sample boxes are shown.")
    return {
        "mode": settings.mode,
        "demo_data": demo_data,
        "disclosure": " ".join(disclosure).strip(),
        "detection": detection,
        "try_on": try_on,
        "search": search,
        "categories": _category_catalog(),
        "reference_kind": settings.youcam_reference_kind if settings.youcam_reference_kind in {"crop", "frame"} else "crop",
        "limits": {
            "max_generations_per_session": settings.max_generations_per_session,
            "max_storage_bytes": settings.max_storage_bytes,
            "max_upload_bytes": settings.max_upload_bytes,
        },
        "prompts": list(ALLOWED_PROMPTS),
        "external_processing": "Trying an item on sends the current photo and the selected reference image to the try-on provider. Product search sends the item crop, not your portrait.",
    }


def _category_catalog() -> dict:
    clothes = {"adapter": "clothes", "gender_required": False, "styles": [], "change_shoes": True}
    return {
        "hat": {"adapter": "hat", "gender_required": True, "styles": sorted(HAT_STYLES), "change_shoes": False},
        "scarf": {"adapter": "scarf", "gender_required": True, "styles": sorted(SCARF_STYLES), "change_shoes": False},
        "bag": {"adapter": "bag", "gender_required": True, "styles": sorted(BAG_STYLES), "change_shoes": False},
        "shoes": {"adapter": "shoes", "gender_required": False, "styles": [], "change_shoes": False},
        "outerwear": {**clothes, "change_shoes": False},
        "upper_body": {**clothes, "change_shoes": False},
        "lower_body": clothes,
        "full_body": clothes,
    }

