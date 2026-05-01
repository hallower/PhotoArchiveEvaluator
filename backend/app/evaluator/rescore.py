"""기존 임베딩을 재사용해 prompt 점수만 빠르게 재계산.

prompt가 바뀌어도 사진 임베딩은 유지되므로 CLIP forward 없이 cosine 만 계산하면 된다.
대량 사진(수만)도 수 초 안에 재평가 가능.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..ai.embed import EmbeddingModel, cosine_similarity
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
