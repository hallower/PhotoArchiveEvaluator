"""기존 photos에 캡션 + 태그 백필.

캡션이 없는 사진(evaluations에 caption=NULL이거나 evaluation 자체가 없음)에 대해
Florence-2 캡션 + CLIP 태그를 추가. CLIP 임베딩은 이미 있으므로 캡션 forward만 필요.

사용법
  python -m scripts.backfill_caption_tags [--limit N]
"""

from __future__ import annotations

import logging
from pathlib import Path

import click
from sqlalchemy import select

from app.evaluator.worker import (
    _upsert_tags,
    default_caption_model,
    default_embed_model,
    default_tag_model,
)
from app.nas.session import open_dsm_client
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
@click.option("--limit", type=int, default=None)
@click.option("--log-level", default="INFO")
def main(limit: int | None, log_level: str) -> None:
    logging.basicConfig(level=log_level, format="%(levelname)s %(name)s: %(message)s")

    click.echo("[*] CLIP 태거 (텍스트 임베딩 사전계산) 로드...")
    tagger = default_tag_model()
    click.echo("[*] Florence-2 캡션 모델 로드...")
    captioner = default_caption_model()
    embed = default_embed_model()  # noqa: F841 — ensure loaded for fallback path

    # 처리 대상: caption 없는 photos (각 photo의 최신 미학 평가가 caption=NULL)
    with SessionLocal() as s:
        # 모든 photo + 최신 aesthetic eval의 caption 조회
        latest_aest_sub = (
            select(Evaluation.photo_id, Evaluation.id)
            .where(Evaluation.model_id != "clip-prompt")
            .order_by(Evaluation.photo_id, Evaluation.id.desc())
            .subquery()
        )
        rows = s.execute(
            select(Photo.id, Evaluation.caption)
            .join(Evaluation, Evaluation.photo_id == Photo.id, isouter=True)
            .where(
                (Evaluation.id == None)  # noqa: E711
                | (Evaluation.caption == None)  # noqa: E711
                | (Evaluation.caption == "")
            )
            .where(Photo.state == "active")
            .distinct()
        ).all()
    todo_ids = sorted(set(r[0] for r in rows))
    if limit:
        todo_ids = todo_ids[:limit]
    click.echo(f"[*] {len(todo_ids)} photos missing caption")

    dsm = None
    done = 0
    failed = 0
    try:
        for pid in todo_ids:
            with SessionLocal() as s:
                pp = s.execute(
                    select(PhotoPath).where(PhotoPath.photo_id == pid).limit(1)
                ).scalar_one_or_none()
                emb_row = s.execute(
                    select(Embedding).where(
                        Embedding.photo_id == pid,
                        Embedding.model_id == "clip",
                        Embedding.model_version == "vit-l-14",
                    )
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
                    cap = captioner.caption(content)
                except Exception as exc:  # noqa: BLE001
                    click.echo(f"  [!] caption fail pid={pid}: {exc}", err=True)
                    failed += 1
                    continue

                if emb_row is not None:
                    tag_result = tagger.tag_from_embedding(emb_row.vector)
                else:
                    # 임베딩 없는 사진은 raw 이미지로 (백필 시 드물게)
                    tag_result = tagger.tag_from_image(content)

                # 최신 aesthetic eval 행에 caption 채우기 — 없으면 새로 만들기
                latest = s.execute(
                    select(Evaluation)
                    .where(
                        Evaluation.photo_id == pid,
                        Evaluation.model_id != "clip-prompt",
                    )
                    .order_by(Evaluation.id.desc())
                    .limit(1)
                ).scalar_one_or_none()
                if latest is not None and not latest.caption:
                    latest.caption = cap.caption
                    latest.caption_lang = cap.lang
                else:
                    # caption-only 행 추가 (드물게, aesthetic eval 자체가 없는 경우)
                    s.add(
                        Evaluation(
                            photo_id=pid,
                            model_id=cap.model_id,
                            model_version=cap.model_version,
                            caption=cap.caption,
                            caption_lang=cap.lang,
                        )
                    )

                _upsert_tags(s, pid, tag_result.tags)
                s.commit()
                done += 1
                if done % 25 == 0:
                    click.echo(f"    progress: {done}/{len(todo_ids)}")
    finally:
        if dsm is not None:
            try:
                dsm.logout()
            finally:
                dsm._client.close()

    click.echo(f"\n[+] captioned: {done}  failed: {failed}")


if __name__ == "__main__":
    main()
