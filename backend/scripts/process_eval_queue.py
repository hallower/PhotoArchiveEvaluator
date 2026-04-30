"""eval_jobs(state='pending') 큐를 워커로 처리.

사용법
  python -m scripts.process_eval_queue [--max-jobs N] [--device cuda|cpu]
"""

from __future__ import annotations

import logging

import click

from app.evaluator.worker import EvaluatorWorker
from app.storage.db import SessionLocal
from app.storage.models import Evaluation


@click.command()
@click.option("--max-jobs", type=int, default=None, help="처리 최대 잡 수 (기본: 큐 소진까지)")
@click.option("--device", default=None, help="cuda 또는 cpu (None이면 자동)")
@click.option("--log-level", default="INFO")
def main(max_jobs: int | None, device: str | None, log_level: str) -> None:
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    score_model = None
    if device is not None:
        from app.ai.local.aesthetic import AestheticV25

        score_model = AestheticV25(device=device)

    worker = EvaluatorWorker(SessionLocal, score_model=score_model)
    n = worker.run(max_jobs=max_jobs)
    click.echo(f"\n[+] processed {n} jobs")

    with SessionLocal() as s:
        rows = s.execute(
            Evaluation.__table__.select()
            .order_by(Evaluation.id.desc())
            .limit(min(n, 200))
        ).fetchall()

    if rows:
        hist = [0] * 5
        for row in rows:
            if row.ai_score is None:
                continue
            bucket = min(4, max(0, int(row.ai_score) - 1))
            hist[bucket] += 1
        total = sum(hist)
        click.echo("\nrecent score distribution (last batch):")
        for i, c in enumerate(hist, start=1):
            bar = "#" * int(40 * c / max(total, 1))
            click.echo(f"  {i}: {c:5d}  {bar}")


if __name__ == "__main__":
    main()
