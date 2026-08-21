"""add forecast tables (sales_actuals, forecast_runs)

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-08-21 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, Sequence[str], None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'sales_actuals',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('period', sa.String(7), nullable=False, comment='期间 YYYY-MM'),
        sa.Column('channel', sa.String(10), nullable=False, comment='渠道 online/offline'),
        sa.Column('units', sa.String(40), nullable=False, comment='销量（万台，Decimal 字符串）'),
        sa.Column('source', sa.String(20), nullable=True, comment='来源：seed/manual/import'),
        sa.Column('note', sa.String(200), nullable=True, comment='备注'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('period', 'channel', name='uq_sales_actual'),
    )
    op.create_table(
        'forecast_runs',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('scenario_id', sa.Integer(), nullable=False, comment='情景ID'),
        sa.Column('method', sa.String(20), nullable=False,
                  comment='plan_anchored/seasonal_naive/holt_winters/sarima'),
        sa.Column('horizon_start', sa.String(7), nullable=False, comment='预测起 YYYY-MM'),
        sa.Column('horizon_end', sa.String(7), nullable=False, comment='预测止 YYYY-MM'),
        sa.Column('n_actual', sa.Integer(), nullable=True, comment='有效历史月数（总量>0）'),
        sa.Column('metrics_json', sa.Text(), nullable=True,
                  comment='{chosen,reason,candidates:{method:{smape,mae,rmse}}}'),
        sa.Column('base_version', sa.Integer(), nullable=True, comment='中性版本号'),
        sa.Column('lower_version', sa.Integer(), nullable=True, comment='悲观版本号'),
        sa.Column('upper_version', sa.Integer(), nullable=True, comment='乐观版本号'),
        sa.Column('created_by', sa.Integer(), nullable=True, comment='创建人用户ID'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_forecast_runs_scenario_id', 'forecast_runs', ['scenario_id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_forecast_runs_scenario_id', table_name='forecast_runs')
    op.drop_table('forecast_runs')
    op.drop_table('sales_actuals')
