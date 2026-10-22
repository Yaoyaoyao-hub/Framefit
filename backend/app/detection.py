"""YOLOWorld detection, with a disclosed fixture path for demo mode."""

from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path
from typing import Any

from app.categories import internal_category
from app.config import get_settings
from app.errors import APIError

_model = None
_model_error: str | None = None
_model_lock = threading.Lock()
_infer_semaphore: threading.BoundedSemaphore | None = None


def detection_status() -> dict[str, Any]:
    settings = get_settings()
    if settings.mode == "demo":
        return {"available": True, "source": "fixture", "model": None, "detail": "Demo detection uses sample boxes."}
    if _model is not None:
        return {"available": True, "source": "yolo", "model": settings.yolo_model, "detail": None}
    if _model_error and settings.mode == "real":
        return {"available": False, "source": "yolo", "model": settings.yolo_model, "detail": "Automatic detection is unavailable. You can draw a box yourself."}
    if settings.mode == "mixed" and _model_error:
        return {"available": True, "source": "fixture", "model": settings.yolo_model, "detail": "The detection model is not loaded, so sample boxes are shown."}
    return {"available": settings.mode != "real", "source": "yolo" if settings.mode == "real" else "pending", "model": settings.yolo_model, "detail": None}


def warm_model() -> None:
    settings = get_settings()
    if settings.mode == "demo":
        return
    try:
        _load_model()
    except Exception:
        return


def detect(image_bytes: bytes, width: int, height: int) -> list[dict]:
    settings = get_settings()
    if settings.mode == "demo":
        return fixture_boxes()
    config_key = _cache_key(image_bytes)
    cached = _read_cache(config_key)
    if cached is not None:
        return _keep_highest_per_label(cached)
    try:
        results = _keep_highest_per_label(_predict(image_bytes, width, height))
    except APIError:
        raise
    except Exception as exc:
        if settings.mode == "mixed":
            return fixture_boxes()
        raise APIError(503, "detection_unavailable", "Automatic detection is unavailable. You can draw a box yourself.") from exc
    _write_cache(config_key, results)
    return results


def fixture_boxes() -> list[dict]:
    prompts = [
        ("hat", 0.91, 0.34, 0.04, 0.28, 0.12),
        ("jacket", 0.86, 0.30, 0.18, 0.40, 0.28),
        ("shoe", 0.84, 0.32, 0.78, 0.36, 0.14),
        ("dress", 0.62, 0.28, 0.2, 0.44, 0.55),
    ]
    items = []
    for prompt, confidence, x, y, w, h in prompts:
        items.append(
            {
                "category_prompt": prompt,
                "internal_category": internal_category(prompt),
                "confidence": confidence,
                "x": x,
                "y": y,
                "width": w,
                "height": h,
            }
        )
    return items


def _keep_highest_per_label(items: list[dict]) -> list[dict]:
    """One box per shown name. Shirt and sweater both read as Upper body, so the higher score wins."""
    best: dict[str, dict] = {}
    for item in items:
        key = str(item["internal_category"])
        current = best.get(key)
        if current is None or float(item["confidence"]) > float(current["confidence"]):
            best[key] = item
    return sorted(best.values(), key=lambda item: float(item["confidence"]), reverse=True)


def _cache_key(image_bytes: bytes) -> str:
    settings = get_settings()
    raw = "|".join(
        [
            hashlib.sha256(image_bytes).hexdigest(),
            settings.mode,
            settings.yolo_model,
            settings.yolo_device,
            str(settings.yolo_confidence),
            str(settings.yolo_image_size),
            ",".join(settings.class_prompts),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _read_cache(key: str) -> list[dict] | None:
    from app.db import SessionLocal
    from app.models import DetectionCache

    if SessionLocal is None:
        return None
    db = SessionLocal()
    try:
        row = db.get(DetectionCache, key)
        if not row:
            return None
        return json.loads(row.result_json)
    finally:
        db.close()


def _write_cache(key: str, results: list[dict]) -> None:
    from app.db import SessionLocal
    from app.models import DetectionCache

    if SessionLocal is None:
        return
    db = SessionLocal()
    try:
        if db.get(DetectionCache, key) is None:
            db.add(DetectionCache(cache_key=key, result_json=json.dumps(results)))
            db.commit()
    finally:
        db.close()


def _semaphore() -> threading.BoundedSemaphore:
    global _infer_semaphore
    if _infer_semaphore is None:
        _infer_semaphore = threading.BoundedSemaphore(max(1, get_settings().yolo_concurrency))
    return _infer_semaphore


def _weight_path() -> str:
    settings = get_settings()
    configured = Path(settings.yolo_model)
    if configured.is_file():
        return str(configured.resolve())
    cache = Path(settings.yolo_cache_dir).resolve()
    cache.mkdir(parents=True, exist_ok=True)
    return str(cache / configured.name)


def _load_model():
    global _model, _model_error
    with _model_lock:
        if _model is not None:
            return _model
        settings = get_settings()
        try:
            import os

            os.environ.setdefault("YOLO_CONFIG_DIR", str(Path(settings.yolo_cache_dir).resolve()))
            from ultralytics import YOLOWorld

            model = YOLOWorld(_weight_path())
            model.set_classes(settings.class_prompts)
            _model = model
            _model_error = None
            return model
        except Exception as exc:
            _model_error = str(exc)
            raise


def _predict(image_bytes: bytes, width: int, height: int) -> list[dict]:
    from io import BytesIO

    import numpy as np
    from PIL import Image

    model = _load_model()
    settings = get_settings()
    image = Image.open(BytesIO(image_bytes)).convert("RGB")
    array = np.array(image)
    semaphore = _semaphore()
    acquired = semaphore.acquire(timeout=120)
    if not acquired:
        raise APIError(429, "busy", "Detection is busy. Try again in a moment.")
    try:
        predictions = model.predict(
            source=array,
            conf=settings.yolo_confidence,
            imgsz=settings.yolo_image_size,
            device=settings.yolo_device,
            verbose=False,
        )
    finally:
        semaphore.release()
    items: list[dict] = []
    if not predictions:
        return items
    result = predictions[0]
    boxes = getattr(result, "boxes", None)
    if boxes is None or boxes.xyxy is None:
        return items
    names = result.names or {}
    for xyxy, conf, cls in zip(boxes.xyxy.tolist(), boxes.conf.tolist(), boxes.cls.tolist()):
        prompt = str(names.get(int(cls), "")).strip().lower()
        if not prompt:
            continue
        try:
            category = internal_category(prompt)
        except APIError:
            continue
        x0, y0, x1, y1 = xyxy
        bw = max(0.0, (x1 - x0) / max(width, 1))
        bh = max(0.0, (y1 - y0) / max(height, 1))
        items.append(
            {
                "category_prompt": prompt if prompt != "shoes" else "shoe",
                "internal_category": category,
                "confidence": float(conf),
                "x": max(0.0, min(1.0, x0 / max(width, 1))),
                "y": max(0.0, min(1.0, y0 / max(height, 1))),
                "width": max(0.0, min(1.0, bw)),
                "height": max(0.0, min(1.0, bh)),
            }
        )
    return items
