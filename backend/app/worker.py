"""Single background worker for try-on jobs."""

from __future__ import annotations

import threading

from app.config import get_settings
from app.db import open_session
from app.domain import mark_interrupted, process_job
from app.models import TryOnJob

_stop = threading.Event()
_thread: threading.Thread | None = None


def start_background() -> None:
    reconcile_jobs()
    if not get_settings().framefit_worker:
        return
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="framefit-jobs", daemon=True)
    _thread.start()


def stop_background() -> None:
    _stop.set()


def reconcile_jobs() -> None:
    db = open_session()
    try:
        jobs = db.query(TryOnJob).filter(TryOnJob.status.in_(["queued", "running"])).all()
        snapshot = [(job.id, job.provider, job.provider_task_id, job.internal_category) for job in jobs]
    finally:
        db.close()
    settings = get_settings()
    for job_id, provider, task_id, category in snapshot:
        if provider == "youcam" and task_id and settings.mode != "demo" and settings.youcam_configured:
            _reconcile_youcam(job_id, category, task_id)
        elif provider != "youcam":
            process_job(job_id, resume=True)
        else:
            mark_interrupted(job_id)


def _reconcile_youcam(job_id: str, category: str, task_id: str) -> None:
    from app.images import prepare_upload
    from app.providers.youcam import YouCamClient, task_path

    settings = get_settings()
    client = YouCamClient(settings.youcam_api_key, settings.youcam_base_url)
    try:
        state, url = client.check_task(task_path(category), task_id)
        if state == "success":
            image = client.download_result(url)
            from app.domain import _commit_success

            db = open_session()
            try:
                _commit_success(db, job_id, prepare_upload(image), {"provider": "youcam", "provider_task_id": task_id})
            finally:
                db.close()
            return
    except Exception:
        mark_interrupted(job_id)
        return
    finally:
        client.close()
    mark_interrupted(job_id)


def _loop() -> None:
    while not _stop.is_set():
        job_id = _next_job_id()
        if job_id:
            process_job(job_id)
        _stop.wait(0.4)


def _next_job_id() -> str | None:
    db = open_session()
    try:
        running = db.query(TryOnJob).filter(TryOnJob.status == "running").count()
        if running >= max(1, get_settings().max_job_concurrency):
            return None
        job = db.query(TryOnJob).filter(TryOnJob.status == "queued").order_by(TryOnJob.created_at.asc()).first()
        return job.id if job else None
    finally:
        db.close()
