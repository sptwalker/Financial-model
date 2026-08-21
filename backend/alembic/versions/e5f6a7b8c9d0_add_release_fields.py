"""add release fields to model_versions

Revision ID: e5f6a7b8c9d0
Revises: c3d4e5f6a7b8
Create Date: 2026-08-21 06:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e5f6a7b8c9d0'
down_revision: Union[str, Sequence[str], None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('model_versions', sa.Column('released_at', sa.DateTime(), nullable=True,
                                              comment='发布时间（非空=已发布；软冻结，可撤销）'))
    op.add_column('model_versions', sa.Column('released_by', sa.Integer(), nullable=True,
                                              comment='发布人用户ID'))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('model_versions', 'released_by')
    op.drop_column('model_versions', 'released_at')
