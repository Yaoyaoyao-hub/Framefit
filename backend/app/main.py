"""FrameFit HTTP API."""

from __future__ import annotations

import time
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, File, Form, Header, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db, init_db, open_session
from app.detection import warm_model
from app.domain import (
    acknowledge_result,
    create_frame,
    create_manual_item,
    create_photo_session,
    create_try_on,
    delete_session,
    delete_version,
    detect_frame,
    get_frame,
    get_job,
    get_session,
    get_version,
    list_sessions,
    public_capabilities,
    read_asset,
    reload_session,
    reset_look,
    sample_bytes,
    search_item,
    serialize_frame,
    serialize_job,
    serialize_session,
    serialize_version,
    set_active,
    undo,
    update_item,
)
from app.errors import APIError
from app.models import Asset, Workspace
from app.security import hash_token, new_token, verify_asset_signature
from app.worker import start_background, stop_background

_hits: dict[str, list[float]] = {}


class ProductBody(BaseModel):
    title: str = "Untitled result"
    source: str | None = None
    url: str
    image: str | None = None
    price: float | None = None
    currency: str | None = None
    result_type: str = "similar_style"


class TryOnBody(BaseModel):
    expected_revision: int
    idempotency_key: str = Field(min_length=8, max_length=80)
    origin: str
    item_id: str | None = None
    category: str | None = None
    reference_kind: str | None = None
    gender: str | None = None
    style: str | None = None
    change_shoes: bool = False
    filter_multi_person: str = "off"
    product: ProductBody | None = None
    demo_fail: bool = False


class ActiveBody(BaseModel):
    version_id: str


class VideoSourceBody(BaseModel):
    url: str


class ItemBody(BaseModel):
    category: str
    x: float
    y: float
    width: float
    height: float


class ItemPatch(BaseModel):
    category: str | None = None
    x: float | None = None
    y: float | None = None
    width: float | None = None
    height: float | None = None


def _limit(key: str) -> None:
    limit = get_settings().rate_limit_per_minute
    now = time.monotonic()
    bucket = [stamp for stamp in _hits.get(key, []) if now - stamp < 60]
    if len(bucket) >= limit:
        raise APIError(429, "busy", "Too many requests. Wait a moment and try again.")
    bucket.append(now)
    _hits[key] = bucket


def workspace(
    request: Request,
    db: Session = Depends(get_db),
    x_workspace_token: str | None = Header(default=None),
) -> Workspace:
    _limit(request.client.host if request.client else "local")
    if not x_workspace_token:
        raise APIError(401, "unauthorized", "This browser session is not recognized. Refresh and try again.")
    row = db.query(Workspace).filter_by(token_hash=hash_token(x_workspace_token)).one_or_none()
    if not row:
        raise APIError(401, "unauthorized", "This browser session is not recognized. Refresh and try again.")
    return row


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    start_background()
    warmer = __import__("threading").Thread(target=warm_model, name="framefit-model", daemon=True)
    warmer.start()
    yield
    stop_background()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="FrameFit", version="1.0.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(APIError)
    async def _api_error(_request: Request, exc: APIError):
        return JSONResponse(status_code=exc.status_code, content={"error": {"code": exc.code, "message": exc.message}})

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    @app.get("/api/ready")
    def ready():
        db = open_session()
        try:
            db.execute(text("SELECT 1"))
        except Exception as exc:
            raise APIError(503, "unavailable", "FrameFit is still starting.") from exc
        finally:
            db.close()
        return {"status": "ready"}

    @app.get("/api/capabilities")
    def capabilities():
        return public_capabilities()

    @app.post("/api/workspaces", status_code=201)
    def create_workspace(request: Request, db: Session = Depends(get_db)):
        from app.domain import new_id

        _limit(f"workspace:{request.client.host if request.client else 'local'}")
        token = new_token()
        row = Workspace(id=new_id(), token_hash=hash_token(token))
        db.add(row)
        db.commit()
        return {"workspace_id": row.id, "token": token}

    @app.get("/api/demo/samples/{kind}")
    def demo_sample(kind: str, _workspace: Workspace = Depends(workspace)):
        if get_settings().mode == "real":
            raise APIError(404, "not_found", "Sample images are hidden when live results are selected.")
        if kind not in {"person", "inspiration"}:
            raise APIError(404, "not_found", "That sample is not available.")
        return Response(content=sample_bytes(kind), media_type="image/jpeg")

    @app.post("/api/photo-sessions", status_code=201)
    async def post_session(file: UploadFile = File(), db: Session = Depends(get_db), owner: Workspace = Depends(workspace)):
        data = await file.read()
        session = create_photo_session(db, owner.id, data)
        return serialize_session(db, session)

    @app.get("/api/photo-sessions")
    def get_sessions(db: Session = Depends(get_db), owner: Workspace = Depends(workspace)):
        return {"sessions": [serialize_session(db, session, include_versions=False) for session in list_sessions(db, owner.id)]}

    @app.get("/api/photo-sessions/{session_id}")
    def get_one_session(session_id: str, db: Session = Depends(get_db), owner: Workspace = Depends(workspace)):
        return serialize_session(db, get_session(db, owner.id, session_id))

    @app.delete("/api/photo-sessions/{session_id}")
    def remove_session(session_id: str, db: Session = Depends(get_db), owner: Workspace = Depends(workspace)):
        delete_session(db, owner.id, session_id)
        return {"deleted": True}

    @app.post("/api/photo-sessions/{session_id}/active")
    def choose_active(session_id: str, body: ActiveBody, db: Session = Depends(get_db), owner: Workspace = Depends(workspace)):
        session = set_active(db, get_session(db, owner.id, session_id), body.version_id)
        return serialize_session(db, session)

    @app.post("/api/photo-sessions/{session_id}/undo")
    def post_undo(session_id: str, db: Session = Depends(get_db), owner: Workspace = Depends(workspace)):
        return serialize_session(db, undo(db, get_session(db, owner.id, session_id)))

    @app.post("/api/photo-sessions/{session_id}/reset")
    def post_reset(session_id: str, db: Session = Depends(get_db), owner: Workspace = Depends(workspace)):
        return serialize_session(db, reset_look(db, get_session(db, owner.id, session_id)))

    @app.post("/api/photo-sessions/{session_id}/reload")
    def post_reload(session_id: str, db: Session = Depends(get_db), owner: Workspace = Depends(workspace)):
        return serialize_session(db, reload_session(db, get_session(db, owner.id, session_id)))

    @app.post("/api/photo-sessions/{session_id}/acknowledge-result")
    def post_ack(session_id: str, db: Session = Depends(get_db), owner: Workspace = Depends(workspace)):
        return serialize_session(db, acknowledge_result(db, get_session(db, owner.id, session_id)))

    @app.post("/api/photo-sessions/{session_id}/inspiration-frames", status_code=201)
    async def post_frame(
        session_id: str,
        file: UploadFile = File(),
        source_kind: str = Form("upload"),
        source_url: str = Form(""),
        db: Session = Depends(get_db),
        owner: Workspace = Depends(workspace),
    ):
        cleaned = source_url.strip() or None
        if cleaned:
            from urllib.parse import urlparse

            parsed = urlparse(cleaned)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname or len(cleaned) > 500:
                raise APIError(400, "invalid_link", "Source links need to start with http or https.")
        frame = create_frame(db, owner.id, session_id, await file.read(), source_kind, cleaned)
        return serialize_frame(db, frame)

    @app.post("/api/video-source")
    def post_video_source(body: VideoSourceBody, _owner: Workspace = Depends(workspace)):
        from app.providers.video_source import download_video

        data, media = download_video(body.url)
        return Response(content=data, media_type=media)

    @app.get("/api/inspiration-frames/{frame_id}")
    def get_one_frame(frame_id: str, db: Session = Depends(get_db), owner: Workspace = Depends(workspace)):
        return serialize_frame(db, get_frame(db, owner.id, frame_id))

    @app.post("/api/inspiration-frames/{frame_id}/detect")
    def post_detect(frame_id: str, db: Session = Depends(get_db), owner: Workspace = Depends(workspace)):
        frame = get_frame(db, owner.id, frame_id)
        detect_frame(db, frame)
        return serialize_frame(db, get_frame(db, owner.id, frame_id))

    @app.post("/api/inspiration-frames/{frame_id}/items", status_code=201)
    def post_item(frame_id: str, body: ItemBody, db: Session = Depends(get_db), owner: Workspace = Depends(workspace)):
        frame = get_frame(db, owner.id, frame_id)
        item = create_manual_item(db, frame, body.category, body.x, body.y, body.width, body.height)
        return serialize_frame(db, get_frame(db, owner.id, item.frame_id))

    @app.patch("/api/items/{item_id}")
    def patch_item(item_id: str, body: ItemPatch, db: Session = Depends(get_db), owner: Workspace = Depends(workspace)):
        box = None
        if any(value is not None for value in (body.x, body.y, body.width, body.height)):
            if None in (body.x, body.y, body.width, body.height):
                raise APIError(400, "invalid_box", "Send the full box when you adjust it.")
            box = (body.x, body.y, body.width, body.height)
        item = update_item(db, owner.id, item_id, prompt=body.category, box=box)
        return serialize_frame(db, get_frame(db, owner.id, item.frame_id))

    @app.post("/api/photo-sessions/{session_id}/try-on", status_code=202)
    def post_try_on(session_id: str, body: TryOnBody, db: Session = Depends(get_db), owner: Workspace = Depends(workspace)):
        job = create_try_on(db, owner.id, session_id, body.model_dump())
        return serialize_job(job)

    @app.get("/api/jobs/{job_id}")
    def get_one_job(job_id: str, db: Session = Depends(get_db), owner: Workspace = Depends(workspace)):
        return serialize_job(get_job(db, owner.id, job_id))

    @app.get("/api/versions/{version_id}")
    def get_one_version(version_id: str, db: Session = Depends(get_db), owner: Workspace = Depends(workspace)):
        return serialize_version(get_version(db, owner.id, version_id))

    @app.delete("/api/versions/{version_id}")
    def remove_version(version_id: str, subtree: bool = False, db: Session = Depends(get_db), owner: Workspace = Depends(workspace)):
        session = delete_version(db, owner.id, version_id, subtree)
        return serialize_session(db, session)

    @app.post("/api/items/{item_id}/search")
    def post_search(item_id: str, db: Session = Depends(get_db), owner: Workspace = Depends(workspace)):
        return search_item(db, owner.id, item_id)

    @app.get("/api/assets/{asset_id}/content")
    def asset_content(asset_id: str, exp: str, sig: str, db: Session = Depends(get_db)):
        verify_asset_signature(asset_id, exp, sig)
        asset = db.get(Asset, asset_id)
        if not asset:
            raise APIError(404, "not_found", "That image could not be found.")
        return Response(content=read_asset(asset), media_type=asset.mime, headers={"Cache-Control": "private, max-age=300"})

    return app


app = create_app()
