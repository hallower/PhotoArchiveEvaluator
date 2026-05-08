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
from ..settings_store import get_eval_prompt
from ..storage.models import Embedding, Evaluation
from .worker import (
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
