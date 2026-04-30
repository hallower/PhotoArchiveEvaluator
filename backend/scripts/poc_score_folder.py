"""PoC: 로컬 폴더의 JPG를 미학 평가하고 점수 분포를 출력한다.

목적
  - Aesthetic Predictor V2.5 모델 동작 검증
  - 사용자 사진에 대한 점수 분포 파악
  - SPEC의 표시 임계값(기본 4.0)이 적절한지 사전 검증

사용법
  python -m scripts.poc_score_folder <folder> [--device cuda|cpu] [--out scores.csv]

이 스크립트는 PoC 전용이며, 본격 평가 파이프라인(scanner+evaluator)은
Phase 1 이후 backend/app/evaluator/에 구현된다.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import click
from tqdm import tqdm

from app.ai.local.aesthetic import AestheticV25

JPG_SUFFIXES = {".jpg", ".jpeg"}


def _is_jpg(path: Path) -> bool:
    return path.suffix.lower() in JPG_SUFFIXES


@click.command()
@click.argument("folder", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--device", default=None, help="cuda 또는 cpu (기본: 자동 감지)")
@click.option(
    "--out",
    "out_path",
    type=click.Path(path_type=Path),
    default=Path("poc_scores.csv"),
    help="출력 CSV 경로",
)
@click.option("--limit", type=int, default=None, help="처리할 최대 사진 수")
def main(folder: Path, device: str | None, out_path: Path, limit: int | None) -> None:
    photos = sorted(p for p in folder.rglob("*") if p.is_file() and _is_jpg(p))
    if limit:
        photos = photos[:limit]

    if not photos:
        click.echo(f"No JPG files found in: {folder}", err=True)
        sys.exit(1)

    click.echo(f"[*] {len(photos)} photos to process. Loading model...")
    model = AestheticV25(device=device)
    click.echo(f"[*] device={model.device}, dtype={model.dtype}")

    histogram = [0] * 5  # 1-5점 버킷 (인덱스 0이 1점)
    failures = 0

    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["path", "score", "raw_score"])
        writer.writeheader()

        for path in tqdm(photos, desc="score"):
            try:
                result = model.score(path.read_bytes())
            except Exception as exc:
                tqdm.write(f"[!] failed {path.name}: {exc}")
                failures += 1
                continue

            writer.writerow(
                {
                    "path": str(path.relative_to(folder)),
                    "score": f"{result.score:.3f}",
                    "raw_score": f"{result.raw_score:.3f}",
                }
            )
            bucket = min(4, max(0, int(result.score) - 1))
            histogram[bucket] += 1

    click.echo(f"\n[+] CSV saved: {out_path}")
    click.echo("\nScore distribution (1-5)")
    total = sum(histogram)
    for i, count in enumerate(histogram, start=1):
        bar = "#" * int(40 * count / max(total, 1))
        click.echo(f"  {i}: {count:5d}  {bar}")

    above_4 = histogram[3] + histogram[4]
    pct = 100 * above_4 / max(total, 1)
    click.echo(f"\nAbove threshold (>=4): {above_4} / {total} ({pct:.1f}%)")

    if failures:
        click.echo(f"failed: {failures}", err=True)


if __name__ == "__main__":
    main()
