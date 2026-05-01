"""기존 photos에 CLIP 임베딩 + prompt 점수를 backfill.

이미 임베딩이 있는 photo는 스킵. 한 번만 돌리면 충분하며, 신규 사진은 평가
워커가 자동으로 임베딩까지 함께 처리한다.

사용법
  python -m scripts.backfill_clip [--limit N]
"""

from __future__ import annotations

import io
import json
import logging
import sys
from pathlib import Path

import click
from sqlalchemy import select

from app.ai.embed import cosine_similarity
from app.ai.local.clip import CLIPLocal
from app.evaluator.worker import (
    PROMPT_MODEL_ID,
    PROMPT_MODEL_VERSION,
    _prompt_score,
    _upsert_embedding,
)
from app.nas.session import open_dsm_client
from app.settings_store import get_eval_prompt
from app.storage.db import SessionLocal
from app.storage.models import Embedding, Evaluation, Photo, PhotoPath


def _read(session, pp: PhotoPath, dsm=None):
    if pp.nas_id == "local":
        return Path(pp.path).read_bytes(), dsm
    if pp.nas_id.startswith("dsm:"):
        if dsm is None:
            dsm = open_dsm_client(session)
        return dsm.download(pp.path), dsm
    raise ValueError(f"unsupported nas_id: {pp.nas_id}")


@click.command()
@click.option("--limit", type=int, default=None, help="최대 N장만 처리")
@click.option("--log-level", default="INFO")
def main(limit: int | None, log_level: str) -> None:
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    click.echo("[*] CLIP 모델 로딩...")
    clip = CLIPLocal()
    click.echo(f"    device={clip.device} dtype={clip.dtype}")

    with SessionLocal() as s:
        prompt = get_eval_prompt(s)
    click.echo(f"[*] prompt = {prompt[:80]}...")
    text_vec = clip.embed_text(prompt).vector

    # 임베딩이 없는 사진 조회
    with SessionLocal() as s:
        existing_ids = set(
            r[0]
            for r in s.execute(
                select(Embedding.photo_id).where(
                    Embedding.model_id == "clip",
                    Embedding.model_version == "vit-l-14",
                )
            )
        )
        all_ids = [
            r[0]
            for r in s.execute(
                select(Photo.id).where(Photo.state == "active").order_by(Photo.id)
            )
        ]

    todo = [pid for pid in all_ids if pid not in existing_ids]
    if limit:
        todo = todo[:limit]
    click.echo(f"[*] {len(todo)} photos to embed (skipped {len(all_ids) - len(todo)})")

    dsm = None
    processed = 0
    failed = 0
    try:
        for pid in todo:
            with SessionLocal() as s:
                pp = s.execute(
                    select(PhotoPath).where(PhotoPath.photo_id == pid).limit(1)
                ).scalar_one_or_none()
                if pp is None:
                    failed += 1
                    continue
                try:
                    content, dsm = _read(s, pp, dsm)
                except Exception as exc:  # noqa: BLE001
                    click.echo(f"  [!] read fail pid={pid}: {exc}", err=True)
                    failed += 1
                    continue
                try:
                    emb = clip.embed_image(content)
                    sim = cosine_similarity(emb.vector, text_vec)
                    score = _prompt_score(sim)
                except Exception as exc:  # noqa: BLE001
                    click.echo(f"  [!] embed fail pid={pid}: {exc}", err=True)
                    failed += 1
                    continue

                _upsert_embedding(s, pid, emb)
                s.add(
                    Evaluation(
                        photo_id=pid,
                        model_id=PROMPT_MODEL_ID,
                        model_version=PROMPT_MODEL_VERSION,
                        ai_score=score,
                        raw_score=sim,
                        raw_response=json.dumps({"prompt": prompt}, ensure_ascii=False),
                    )
                )
                s.commit()
            processed += 1
            if processed % 20 == 0:
                click.echo(f"    progress: {processed}/{len(todo)}")
    finally:
        if dsm is not None:
            try:
                dsm.logout()
            finally:
                dsm._client.close()

    click.echo(f"\n[+] embedded: {processed}  failed: {failed}")


if __name__ == "__main__":
    main()
