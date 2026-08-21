"""initial schema

Revision ID: d57d6a3e41c1
Revises:
Create Date: 2026-08-21 03:01:17.310137

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd57d6a3e41c1'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 初始 schema：对应 2026-08-21 各模型的建表（params_json/inputs_json 由后续迁移补充）
    op.create_table(
        'users',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('feishu_user_id', sa.String(100), nullable=False),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('avatar_url', sa.String(500), nullable=True),
        sa.Column('department', sa.String(100), nullable=True),
        sa.Column('role', sa.Enum('admin', 'editor', 'viewer', name='userrole'),
                  nullable=False),
        sa.Column('status', sa.Enum('active', 'disabled', name='userstatus'),
                  nullable=False),
        sa.Column('last_login_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('feishu_user_id'),
    )
    op.create_index('ix_users_status', 'users', ['status'])
    op.create_index('ix_users_feishu_user_id', 'users', ['feishu_user_id'])
    op.create_table(
        'scenarios',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )
    op.create_table(
        'model_versions',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('scenario_id', sa.Integer(), nullable=False),
        sa.Column('version_no', sa.Integer(), nullable=False),
        sa.Column('comment', sa.String(500), nullable=True),
        sa.Column('source', sa.String(20), nullable=True),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('scenario_id', 'version_no', name='uq_model_version'),
    )
    op.create_index('ix_model_versions_scenario_id', 'model_versions', ['scenario_id'])
    op.create_table(
        'cells',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('scenario_id', sa.Integer(), nullable=False),
        sa.Column('model_version', sa.Integer(), nullable=False),
        sa.Column('period', sa.String(7), nullable=False),
        sa.Column('row_key', sa.String(50), nullable=False),
        sa.Column('value', sa.String(40), nullable=False),
        sa.Column('source', sa.String(20), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('scenario_id', 'model_version', 'period', 'row_key', name='uq_cell'),
    )
    op.create_index('ix_cells_scenario_id', 'cells', ['scenario_id'])
    op.create_table(
        'operation_logs',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('action', sa.String(50), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('detail', sa.Text(), nullable=True),
        sa.Column('ip', sa.String(50), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_operation_logs_user_id', 'operation_logs', ['user_id'])
    op.create_index('ix_operation_logs_action', 'operation_logs', ['action'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_operation_logs_action', table_name='operation_logs')
    op.drop_index('ix_operation_logs_user_id', table_name='operation_logs')
    op.drop_table('operation_logs')
    op.drop_index('ix_cells_scenario_id', table_name='cells')
    op.drop_table('cells')
    op.drop_index('ix_model_versions_scenario_id', table_name='model_versions')
    op.drop_table('model_versions')
    op.drop_table('scenarios')
    op.drop_index('ix_users_feishu_user_id', table_name='users')
    op.drop_index('ix_users_status', table_name='users')
    op.drop_table('users')
