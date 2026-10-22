"""Persistent photo sessions, versions, jobs, and assets."""

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Asset(Base):
    __tablename__ = "assets"
    __table_args__ = (UniqueConstraint("workspace_id", "sha256", name="uq_asset_hash"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    storage_key: Mapped[str] = mapped_column(String(255))
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    mime: Mapped[str] = mapped_column(String(64))
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    byte_size: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PhotoSession(Base):
    __tablename__ = "photo_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    original_asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id"))
    root_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    active_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    active_job_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    unseen_result_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    versions: Mapped[list["GenerationVersion"]] = relationship(back_populates="session")


class GenerationVersion(Base):
    __tablename__ = "generation_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("photo_sessions.id"), index=True)
    parent_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    category: Mapped[str | None] = mapped_column(String(32), nullable=True)
    label: Mapped[str] = mapped_column(String(80))
    inspiration_frame_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    detected_item_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    product_snapshot_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    reference_asset_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    settings_json: Mapped[str] = mapped_column(Text, default="{}")
    provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    provider_task_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    app_job_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    origin: Mapped[str] = mapped_column(String(32), default="root")
    is_root: Mapped[bool] = mapped_column(Boolean, default=False)

    session: Mapped[PhotoSession] = relationship(back_populates="versions")


class InspirationFrame(Base):
    __tablename__ = "inspiration_frames"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    session_id: Mapped[str | None] = mapped_column(ForeignKey("photo_sessions.id"), nullable=True, index=True)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id"))
    source_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source_kind: Mapped[str] = mapped_column(String(32), default="upload")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DetectedItem(Base):
    __tablename__ = "detected_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    frame_id: Mapped[str] = mapped_column(ForeignKey("inspiration_frames.id"), index=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    category_prompt: Mapped[str] = mapped_column(String(32))
    internal_category: Mapped[str] = mapped_column(String(32))
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    x: Mapped[float] = mapped_column(Float)
    y: Mapped[float] = mapped_column(Float)
    width: Mapped[float] = mapped_column(Float)
    height: Mapped[float] = mapped_column(Float)
    crop_asset_id: Mapped[str | None] = mapped_column(ForeignKey("assets.id"), nullable=True)
    manual: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DetectionCache(Base):
    __tablename__ = "detection_cache"

    cache_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    result_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TryOnJob(Base):
    __tablename__ = "try_on_jobs"
    __table_args__ = (UniqueConstraint("session_id", "idempotency_key", name="uq_job_idempotency"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("photo_sessions.id"), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(80))
    expected_revision: Mapped[int] = mapped_column(Integer)
    source_version_id: Mapped[str] = mapped_column(String(36))
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    origin: Mapped[str] = mapped_column(String(32))
    internal_category: Mapped[str] = mapped_column(String(32))
    reference_asset_id: Mapped[str] = mapped_column(String(36))
    frame_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    item_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    product_snapshot_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    settings_json: Mapped[str] = mapped_column(Text, default="{}")
    provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    provider_task_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    result_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    retryable: Mapped[bool] = mapped_column(Boolean, default=True)
    applied_to_active: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
