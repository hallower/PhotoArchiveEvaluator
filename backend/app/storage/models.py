"""ORM 모델.

Phase 1 MVP 범위 — photos / photo_paths / evaluations / scan_jobs / eval_jobs /
settings / audit_logs. 나머지(SCHEMA.md의 embeddings, tags, categories,
portfolios, advanced_reviews, user_scores, api_costs, backups)는 Phase 2 이후에
추가한다.

스키마 변경은 alembic revision으로만 한다. 본 파일을 수정하면 새 revision을
생성해야 한다.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import BigInteger, ForeignKey, Index, LargeBinary, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Photo(Base):
    __tablename__ = "photos"

    id: Mapped[int] = mapped_column(primary_key=True)
    sha256: Mapped[str] = mapped_column(unique=True, index=True)
    phash: Mapped[str | None] = mapped_column(index=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    width: Mapped[int | None] = mapped_column(default=None)
    height: Mapped[int | None] = mapped_column(default=None)
    mime_type: Mapped[str]

    # EXIF
    taken_at: Mapped[datetime | None] = mapped_column(index=True, default=None)
    camera_make: Mapped[str | None] = mapped_column(default=None)
    camera_model: Mapped[str | None] = mapped_column(default=None)
    lens_model: Mapped[str | None] = mapped_column(default=None)
    iso: Mapped[int | None] = mapped_column(default=None)
    aperture: Mapped[float | None] = mapped_column(default=None)
    shutter: Mapped[str | None] = mapped_column(default=None)
    focal_mm: Mapped[float | None] = mapped_column(default=None)
    gps_lat: Mapped[float | None] = mapped_column(default=None)
    gps_lon: Mapped[float | None] = mapped_column(default=None)

    # 운영
    state: Mapped[str] = mapped_column(default="active", index=True)
    first_seen_at: Mapped[datetime] = mapped_column(default=_utc_now)
    last_seen_at: Mapped[datetime] = mapped_column(default=_utc_now)
    updated_at: Mapped[datetime] = mapped_column(default=_utc_now, onupdate=_utc_now)

    paths: Mapped[list[PhotoPath]] = relationship(
        back_populates="photo", cascade="all, delete-orphan"
    )
    evaluations: Mapped[list[Evaluation]] = relationship(
        back_populates="photo", cascade="all, delete-orphan"
    )


class PhotoPath(Base):
    __tablename__ = "photo_paths"
    __table_args__ = (UniqueConstraint("nas_id", "path", name="uq_nas_path"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    photo_id: Mapped[int] = mapped_column(
        ForeignKey("photos.id", ondelete="CASCADE"), index=True
    )
    nas_id: Mapped[str]
    path: Mapped[str] = mapped_column(Text)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    mtime: Mapped[datetime]
    last_seen_at: Mapped[datetime] = mapped_column(default=_utc_now)

    photo: Mapped[Photo] = relationship(back_populates="paths")


class Evaluation(Base):
    """기본 평가 결과(점수 무관 모두 저장. 이력 보존)."""

    __tablename__ = "evaluations"
    __table_args__ = (
        Index("idx_eval_photo_model", "photo_id", "model_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    photo_id: Mapped[int] = mapped_column(ForeignKey("photos.id", ondelete="CASCADE"))
    model_id: Mapped[str]
    model_version: Mapped[str]
    ai_score: Mapped[float | None] = mapped_column(default=None)
    raw_score: Mapped[float | None] = mapped_column(default=None)
    """모델 원본 점수. PoC에서 정규화 재캘리브레이션 가능성을 위해 보존 (POC_REPORT 참조)."""
    confidence: Mapped[float | None] = mapped_column(default=None)
    caption: Mapped[str | None] = mapped_column(Text, default=None)
    caption_lang: Mapped[str | None] = mapped_column(default=None)
    composition: Mapped[str | None] = mapped_column(Text, default=None)
    color_analysis: Mapped[str | None] = mapped_column(Text, default=None)
    raw_response: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(default=_utc_now)

    photo: Mapped[Photo] = relationship(back_populates="evaluations")


class Embedding(Base):
    """사진 임베딩 벡터.

    동일 (photo_id, model_id, model_version)는 1행만 활성. 모델 교체 시 재계산.
    Phase 1에서는 CLIP image embedding을 저장. text embedding은 prompt 변경 시
    런타임에서만 계산하므로 저장 안 함.
    """

    __tablename__ = "embeddings"
    __table_args__ = (
        UniqueConstraint(
            "photo_id", "model_id", "model_version", name="uq_emb_photo_model"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    photo_id: Mapped[int] = mapped_column(ForeignKey("photos.id", ondelete="CASCADE"), index=True)
    model_id: Mapped[str]
    model_version: Mapped[str]
    dim: Mapped[int]
    vector: Mapped[bytes] = mapped_column(LargeBinary)  # float32 packed
    created_at: Mapped[datetime] = mapped_column(default=_utc_now)


class ScanJob(Base):
    __tablename__ = "scan_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    started_at: Mapped[datetime] = mapped_column(default=_utc_now)
    finished_at: Mapped[datetime | None] = mapped_column(default=None)
    state: Mapped[str]  # pending | running | done | failed
    folders: Mapped[str] = mapped_column(Text)  # JSON 배열
    discovered: Mapped[int] = mapped_column(default=0)
    new_photos: Mapped[int] = mapped_column(default=0)
    changed: Mapped[int] = mapped_column(default=0)
    skipped: Mapped[int] = mapped_column(default=0)
    error: Mapped[str | None] = mapped_column(Text, default=None)


class EvalJob(Base):
    """평가 작업 단위(상태 트랜잭션, 재개 가능)."""

    __tablename__ = "eval_jobs"
    __table_args__ = (
        Index("idx_evaljobs_state_prio", "state", "priority", "enqueued_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    photo_id: Mapped[int] = mapped_column(ForeignKey("photos.id", ondelete="CASCADE"))
    kind: Mapped[str]  # 'basic' | 'advanced'
    priority: Mapped[int] = mapped_column(default=0)
    state: Mapped[str]  # pending | in_progress | done | failed
    attempts: Mapped[int] = mapped_column(default=0)
    last_error: Mapped[str | None] = mapped_column(Text, default=None)
    enqueued_at: Mapped[datetime] = mapped_column(default=_utc_now)
    started_at: Mapped[datetime | None] = mapped_column(default=None)
    finished_at: Mapped[datetime | None] = mapped_column(default=None)


class UserScore(Base):
    """사용자 점수 오버라이드 (SCHEMA §2.9). photo 당 1행."""

    __tablename__ = "user_scores"

    photo_id: Mapped[int] = mapped_column(
        ForeignKey("photos.id", ondelete="CASCADE"), primary_key=True
    )
    score: Mapped[float]  # 1.0 - 5.0
    note: Mapped[str | None] = mapped_column(Text, default=None)
    updated_at: Mapped[datetime] = mapped_column(default=_utc_now, onupdate=_utc_now)


class Setting(Base):
    """런타임 설정. config.py와 분리 — 런타임 변경 가능 항목만 여기에 둔다."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(default=_utc_now, onupdate=_utc_now)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    actor: Mapped[str]  # 'system' | 'user'
    event: Mapped[str]
    detail: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(default=_utc_now, index=True)
