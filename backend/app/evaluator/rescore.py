"""기존 임베딩을 재사용해 prompt 점수만 빠르게 재계산.

prompt가 바뀌어도 사진 임베딩은 유지되므로 CLIP forward 없이 cosine 만 계산하면 된다.
대량 사진(수만)도 수 초 안에 재평가 가능.

또한 미학(aesthetic) 점수의 정규화 공식이 바뀌었을 때 raw_score로부터
ai_score를 재계산하는 헬퍼도 제공한다 (모델 forward 없이 곱셈만 — 매우 빠름).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..ai.embed import EmbeddingModel, cosine_similarity
from ..ai.local.aesthetic import MODEL_ID as AESTHETIC_MODEL_ID
from ..ai.local.aesthetic import normalize_raw as aesthetic_normalize
from ..settings_store import get_documentary_prompt, get_eval_prompt
from ..storage.models import Embedding, EvalJob, Evaluation, Photo
from .worker import (
    DOCUMENTARY_MODEL_ID,
    DOCUMENTARY_MODEL_VERSION,
    PROMPT_MODEL_ID,
    PROMPT_MODEL_VERSION,
    _prompt_score,
    default_embed_model,
)

log = logging.getLogger(__name__)


def rescore_prompt(
    session_factory: Callable[[], Session],
    embed_model: EmbeddingModel | None = None,
) -> int:
    """모든 photo에 대해 prompt 점수를 재계산. 추가된 evaluations 행 수 반환."""
    model = embed_model or default_embed_model()

    with session_factory() as s:
        prompt = get_eval_prompt(s)
    text_vec = model.embed_text(prompt).vector

    added = 0
    with session_factory() as s:
        rows = s.execute(
            select(Embedding).where(
                Embedding.model_id == "clip",
                Embedding.model_version == "vit-l-14",
            )
        ).scalars().all()
        for emb in rows:
            sim = cosine_similarity(emb.vector, text_vec)
            score = _prompt_score(sim)
            s.add(
                Evaluation(
                    photo_id=emb.photo_id,
                    model_id=PROMPT_MODEL_ID,
                    model_version=PROMPT_MODEL_VERSION,
                    ai_score=score,
                    raw_score=sim,
                    raw_response=json.dumps({"prompt": prompt}, ensure_ascii=False),
                )
            )
            added += 1
        s.commit()
    log.info("prompt rescore: added=%d evaluations", added)
    return added


def rescore_documentary(
    session_factory: Callable[[], Session],
    embed_model: EmbeddingModel | None = None,
) -> int:
    """저장된 image embedding으로 documentary 점수만 재계산. CLIP forward 1회 (text)만.

    임베딩이 없는 사진은 처리할 수 없다. 그런 사진까지 커버하려면
    `ensure_documentary_coverage()`를 사용.
    """
    model = embed_model or default_embed_model()

    with session_factory() as s:
        prompt = get_documentary_prompt(s)
    text_vec = model.embed_text(prompt).vector

    added = 0
    with session_factory() as s:
        rows = s.execute(
            select(Embedding).where(
                Embedding.model_id == "clip",
                Embedding.model_version == "vit-l-14",
            )
        ).scalars().all()
        for emb in rows:
            sim = cosine_similarity(emb.vector, text_vec)
            score = _prompt_score(sim)
            s.add(
                Evaluation(
                    photo_id=emb.photo_id,
                    model_id=DOCUMENTARY_MODEL_ID,
                    model_version=DOCUMENTARY_MODEL_VERSION,
                    ai_score=score,
                    raw_score=sim,
                    raw_response=json.dumps({"prompt": prompt}, ensure_ascii=False),
                )
            )
            added += 1
        s.commit()
    log.info("documentary rescore: added=%d evaluations", added)
    return added


def ensure_documentary_coverage(
    session_factory: Callable[[], Session],
    embed_model: EmbeddingModel | None = None,
) -> dict:
    """모든 active 사진에 documentary 점수가 보장되도록 한다 (공격적 모드).

    단계별:
    1) 임베딩이 있는 사진 → cosine으로 즉시 doc 점수 추가 (rescore_documentary 위임).
       이전에 doc 점수가 없던 사진도, 있던 사진도 모두 갱신된 점수가 추가됨.
    2) 임베딩이 없는 active 사진들에 대해:
       a) 이미 pending/in_progress basic 잡 있음 → 그대로 둠 (워커가 처리)
       b) 실패(failed) basic 잡 있음 → pending으로 reset (재시도) + attempts 0
       c) 잡 없음 → 새 basic 잡 큐잉
    3) 마지막에 실제로 doc 점수가 여전히 누락된 active 사진 수를 다시 집계해 보고.

    반환: {"rescored", "reset_failed", "queued_new", "already_queued", "still_missing", "active_total"}
    """
    rescored = rescore_documentary(session_factory, embed_model=embed_model)

    reset_failed = 0
    queued_new = 0
    already_queued = 0

    with session_factory() as s:
        # 임베딩이 없는 active photos
        embed_subq = select(Embedding.photo_id).where(
            Embedding.model_id == "clip",
            Embedding.model_version == "vit-l-14",
        )
        no_embed_ids: list[int] = list(
            s.execute(
                select(Photo.id).where(
                    Photo.state == "active",
                    Photo.id.notin_(embed_subq),
                )
            ).scalars().all()
        )

        if no_embed_ids:
            # 각 photo의 가장 최신 basic eval_job 1건의 상태를 가져와 분기.
            jobs = s.execute(
                select(EvalJob).where(
                    EvalJob.kind == "basic",
                    EvalJob.photo_id.in_(no_embed_ids),
                )
            ).scalars().all()
            latest_job_by_photo: dict[int, EvalJob] = {}
            for j in jobs:
                cur = latest_job_by_photo.get(j.photo_id)
                if cur is None or j.id > cur.id:
                    latest_job_by_photo[j.photo_id] = j

            for pid in no_embed_ids:
                latest = latest_job_by_photo.get(pid)
                if latest is None:
                    s.add(EvalJob(photo_id=pid, kind="basic", state="pending", priority=5))
                    queued_new += 1
                elif latest.state in ("pending", "in_progress"):
                    already_queued += 1
                elif latest.state == "failed":
                    latest.state = "pending"
                    latest.attempts = 0
                    latest.last_error = None
                    latest.started_at = None
                    latest.finished_at = None
                    reset_failed += 1
                else:  # done — 그러나 임베딩이 없다? race / 잘못된 상태 → 새 잡 추가
                    s.add(EvalJob(photo_id=pid, kind="basic", state="pending", priority=5))
                    queued_new += 1
        s.commit()

        # 최종 진단: 여전히 doc 점수가 없는 active 사진 수
        doc_subq = select(Evaluation.photo_id).where(
            Evaluation.model_id == DOCUMENTARY_MODEL_ID
        )
        still_missing = s.execute(
            select(Photo.id).where(
                Photo.state == "active",
                Photo.id.notin_(doc_subq),
            )
        ).scalars().all()

        active_total = s.execute(
            select(Photo.id).where(Photo.state == "active")
        ).scalars().all()

    log.info(
        "documentary coverage: rescored=%d reset_failed=%d queued_new=%d already_queued=%d still_missing=%d active=%d",
        rescored, reset_failed, queued_new, already_queued, len(still_missing), len(active_total),
    )
    return {
        "rescored": rescored,
        "reset_failed": reset_failed,
        "queued_new": queued_new,
        "already_queued": already_queued,
        "still_missing": len(still_missing),
        "still_missing_sample_ids": [int(p) for p in still_missing[:10]],
        "active_total": len(active_total),
    }


def recalibrate_aesthetic(session_factory: Callable[[], Session]) -> int:
    """기존 aesthetic Evaluation 행의 ai_score를 raw_score 기준으로 다시 계산.

    정규화 공식이 바뀌었을 때 모델을 다시 돌리지 않고 DB만 업데이트하는 용도.
    raw_score가 None인 행은 건드리지 않는다. 변경된 행 수 반환.
    """
    updated = 0
    with session_factory() as s:
        rows = (
            s.execute(
                select(Evaluation)
                .where(
                    Evaluation.model_id == AESTHETIC_MODEL_ID,
                    Evaluation.raw_score.is_not(None),
                )
            )
            .scalars()
            .all()
        )
        for ev in rows:
            new_score = aesthetic_normalize(float(ev.raw_score))
            if ev.ai_score != new_score:
                ev.ai_score = new_score
                updated += 1
        s.commit()
    log.info("aesthetic recalibrate: updated=%d evaluations", updated)
    return updated
