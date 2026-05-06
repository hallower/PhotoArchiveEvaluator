"""rescale scores from 1-5 to 0-100

raw_score는 모델 원본(1-10 또는 cosine sim)이므로 그대로 두고, 정규화된
ai_score / user_scores.score / library.min_score 만 0-100 스케일로 변환한다.
변환식: new = (old - 1) * 25 → 1.0→0, 3.0→50, 5.0→100.

Idempotent: 데이터가 이미 100 스케일이면(max > 5) skip.

Revision ID: d4f1c2a8b3e7
Revises: 6e16b8462ac0
Create Date: 2026-05-07 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = 'd4f1c2a8b3e7'
down_revision: Union[str, Sequence[str], None] = '6e16b8462ac0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    eval_max = bind.exec_driver_sql(
        "SELECT MAX(ai_score) FROM evaluations WHERE ai_score IS NOT NULL"
    ).scalar()
    if eval_max is not None and eval_max <= 5.0:
        bind.exec_driver_sql(
            "UPDATE evaluations "
            "SET ai_score = (ai_score - 1.0) * 25.0 "
            "WHERE ai_score IS NOT NULL"
        )

    user_max = bind.exec_driver_sql(
        "SELECT MAX(score) FROM user_scores"
    ).scalar()
    if user_max is not None and user_max <= 5.0:
        bind.exec_driver_sql(
            "UPDATE user_scores SET score = (score - 1.0) * 25.0"
        )

    # library.min_score 설정값도 보정
    row = bind.exec_driver_sql(
        "SELECT value FROM settings WHERE key = 'library.min_score'"
    ).fetchone()
    if row is not None:
        try:
            old = float(row[0])
        except (TypeError, ValueError):
            old = None
        if old is not None and old <= 5.0:
            new_val = max(0.0, min(100.0, (old - 1.0) * 25.0))
            bind.exec_driver_sql(
                "UPDATE settings SET value = :v WHERE key = 'library.min_score'",
                {"v": str(new_val)},
            )


def downgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql(
        "UPDATE evaluations "
        "SET ai_score = (ai_score / 25.0) + 1.0 "
        "WHERE ai_score IS NOT NULL"
    )
    bind.exec_driver_sql(
        "UPDATE user_scores SET score = (score / 25.0) + 1.0"
    )
    row = bind.exec_driver_sql(
        "SELECT value FROM settings WHERE key = 'library.min_score'"
    ).fetchone()
    if row is not None:
        try:
            new = float(row[0])
        except (TypeError, ValueError):
            new = None
        if new is not None and new > 5.0:
            old = max(1.0, min(5.0, (new / 25.0) + 1.0))
            bind.exec_driver_sql(
                "UPDATE settings SET value = :v WHERE key = 'library.min_score'",
                {"v": str(old)},
            )
