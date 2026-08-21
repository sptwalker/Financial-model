"""add params_json to model_versions

Revision ID: a1b2c3d4e5f6
Revises: d57d6a3e41c1
Create Date: 2026-08-21 04:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'd57d6a3e41c1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('model_versions', sa.Column('params_json', sa.Text(), nullable=True,
                                              comment='引擎参数快照（JSON，Decimal 序列化为字符串）'))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('model_versions', 'params_json')
