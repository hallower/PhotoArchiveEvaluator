"""평가 워커.

eval_jobs(state='pending')을 우선순위 순으로 dequeue → AI 어댑터 호출 →
evaluations 행 추가. 실패 시 attempts 증가, MAX_ATTEMPTS 초과 시 'failed' 격리.

재개 정책 (SPEC §5.2)
- 시작 시 in_progress → pending으로 일괄 복구 (recover_pending)
- 잡당 attempts MAX_ATTEMPTS=3
- pending이 비면 종료 (max_jobs를 None으로 하면 큐 소진까지 처리)
"""

from __future__ import annotations

import functools
import logging
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

import json

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..ai.base import ScoreModel
from ..ai.embed import EmbeddingModel, cosine_similarity
from ..nas.dsm import DSMClient
from ..nas.session import open_dsm_client
from ..settings_store import get_eval_prompt
from ..storage.models import Embedding, EvalJob, Evaluation, PhotoPath

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 3


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@functools.cache
def default_score_model() -> ScoreModel:
    """프로세스 1회 로드. AestheticV25는 SigLIP 가중치 다운로드 + GPU 메모리를 차지."""
    from ..ai.local.aesthetic import AestheticV25

    return AestheticV25()


@functools.cache
def default_embed_model() -> EmbeddingModel:
    """프로세스 1회 로드. CLIP ViT-L/14는 약 1.5GB VRAM."""
    from ..ai.local.clip import CLIPLocal

    return CLIPLocal()


PROMPT_MODEL_ID = "clip-prompt"
PROMPT_MODEL_VERSION = "vit-l-14"


def _prompt_score(cosine_sim: float) -> float:
    """CLIP cosine similarity → 1-5 normalized score.

    실측 (137장 사용자 라이브러리, 미학 prompt) — sim 분포는 0.178~0.230에 집중.
    선형 매핑: sim 0.16 → 1점, sim 0.26 → 5점. 일반 prompt 기준으로 라이브러리에서
    상위 사진이 4-5점에 도달할 수 있게 한다. prompt가 더 구체적이면 분포가 위로 이동.
    """
    return max(1.0, min(5.0, (cosine_sim - 0.16) * 40 + 1))


class EvaluatorWorker:
    def __init__(
        self,
        session_factory: Callable[[], Session],
        score_model: ScoreModel | None = None,
        embed_model: EmbeddingModel | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._score_model = score_model
        self._embed_model = embed_model
        self._dsm_client: DSMClient | None = None
        self._prompt_text_cache: tuple[str, bytes] | None = None  # (prompt, text_vec)

    @property
    def model(self) -> ScoreModel:
        if self._score_model is None:
            self._score_model = default_score_model()
        return self._score_model

    @property
    def embed(self) -> EmbeddingModel:
        if self._embed_model is None:
            self._embed_model = default_embed_model()
        return self._embed_model

    def _prompt_text_vector(self, prompt: str) -> bytes:
        """프롬프트의 CLIP text embedding을 캐시. 동일 prompt면 재사용."""
        if self._prompt_text_cache and self._prompt_text_cache[0] == prompt:
            return self._prompt_text_cache[1]
        result = self.embed.embed_text(prompt)
        self._prompt_text_cache = (prompt, result.vector)
        return result.vector

    def run(self, max_jobs: int | None = None) -> int:
        """큐를 처리한다. 처리한 작업 수 반환. pending이 비면 즉시 종료."""
        processed = 0
        try:
            while max_jobs is None or processed < max_jobs:
                with self._session_factory() as s:
                    got_one = self._process_one(s)
                if not got_one:
                    break
                processed += 1
        finally:
            self._close_dsm()
        return processed

    def _close_dsm(self) -> None:
        if self._dsm_client is not None:
            try:
                self._dsm_client.logout()
            finally:
                self._dsm_client._client.close()
                self._dsm_client = None

    def _process_one(self, session: Session) -> bool:
        job = session.execute(
            select(EvalJob)
            .where(EvalJob.state == "pending", EvalJob.kind == "basic")
            .order_by(EvalJob.priority.desc(), EvalJob.enqueued_at)
            .limit(1)
        ).scalar_one_or_none()

        if job is None:
            return False

        # 잠금 (단일 워커 전제 — 다중 워커 시 SELECT FOR UPDATE / 비교-스왑으로 대체)
        job.state = "in_progress"
        job.started_at = _utc_now()
        job.attempts += 1
        session.commit()

        photo_id = job.photo_id

        try:
            content = self._read_for_photo(session, photo_id)
            score_result = self.model.score(content)
            # CLIP image embedding (저장)
            image_emb = self.embed.embed_image(content)
            # 사용자 prompt와의 cosine similarity → 1-5
            prompt_text = get_eval_prompt(session)
            text_vec = self._prompt_text_vector(prompt_text)
            sim = cosine_similarity(image_emb.vector, text_vec)
            prompt_score = _prompt_score(sim)
        except Exception as exc:  # noqa: BLE001
            log.exception("eval failed for photo %d", photo_id)
            job.last_error = str(exc)[:1000]
            job.finished_at = _utc_now()
            job.state = "failed" if job.attempts >= MAX_ATTEMPTS else "pending"
            if job.state == "pending":
                job.started_at = None
            session.commit()
            return True

        # 1) 미학 점수 (AestheticV25)
        session.add(
            Evaluation(
                photo_id=photo_id,
                model_id=score_result.model_id,
                model_version=score_result.model_version,
                ai_score=score_result.score,
                raw_score=score_result.raw_score,
                confidence=score_result.confidence,
            )
        )
        # 2) CLIP image embedding (upsert)
        _upsert_embedding(session, photo_id, image_emb)
        # 3) prompt 점수 (CLIP cosine)
        session.add(
            Evaluation(
                photo_id=photo_id,
                model_id=PROMPT_MODEL_ID,
                model_version=PROMPT_MODEL_VERSION,
                ai_score=prompt_score,
                raw_score=sim,
                raw_response=json.dumps({"prompt": prompt_text}, ensure_ascii=False),
            )
        )

        job.state = "done"
        job.finished_at = _utc_now()
        session.commit()
        return True

    def _read_for_photo(self, session: Session, photo_id: int) -> bytes:
        pp = session.execute(
            select(PhotoPath).where(PhotoPath.photo_id == photo_id).limit(1)
        ).scalar_one_or_none()
        if pp is None:
            raise RuntimeError(f"photo {photo_id} has no path")
        return self._read_bytes(session, pp)

    def _read_bytes(self, session: Session, pp: PhotoPath) -> bytes:
        if pp.nas_id == "local":
            path = Path(pp.path)
            if not path.exists():
                raise FileNotFoundError(f"file missing: {path}")
            return path.read_bytes()
        if pp.nas_id.startswith("dsm:"):
            return self._dsm(session).download(pp.path)
        raise ValueError(f"unsupported nas_id: {pp.nas_id}")

    def _dsm(self, session: Session) -> DSMClient:
        if self._dsm_client is None:
            self._dsm_client = open_dsm_client(session)
        return self._dsm_client


def _upsert_embedding(session: Session, photo_id: int, emb) -> None:
    existing = session.execute(
        select(Embedding).where(
            Embedding.photo_id == photo_id,
            Embedding.model_id == emb.model_id,
            Embedding.model_version == emb.model_version,
        )
    ).scalar_one_or_none()
    if existing:
        existing.vector = emb.vector
        existing.dim = emb.dim
        existing.created_at = _utc_now()
    else:
        session.add(
            Embedding(
                photo_id=photo_id,
                model_id=emb.model_id,
                model_version=emb.model_version,
                dim=emb.dim,
                vector=emb.vector,
            )
        )


def recover_pending(session: Session) -> int:
    """시작 시 in_progress → pending 복구 (SPEC §5.2)."""
    stmt = (
        update(EvalJob)
        .where(EvalJob.state == "in_progress")
        .values(state="pending", started_at=None)
    )
    rowcount = session.execute(stmt).rowcount or 0
    session.commit()
    return rowcount
