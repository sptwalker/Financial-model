"""add pending status to userstatus enum

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-08-24 10:00:00.000000

新增用户准入状态 pending（首登待审批）。
- PostgreSQL：原生 ENUM 需 ALTER TYPE ADD VALUE（PG12+ 允许在事务内执行）
- SQLite：SQLAlchemy 默认不建 CHECK 约束（create_constraint=False），无需改动
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'f6a7b8c9d0e1'
down_revision: Union[str, Sequence[str], None] = 'e5f6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # IF NOT EXISTS 保证幂等；PG12+ 支持事务内 ADD VALUE
        op.execute("ALTER TYPE userstatus ADD VALUE IF NOT EXISTS 'pending'")
    # 其它方言（SQLite）：状态列为普通 VARCHAR，无枚举约束，无需迁移


def downgrade() -> None:
    """Downgrade schema."""
    # PostgreSQL 不支持从枚举类型中删除值；pending 保留无副作用。
    pass
