"""per-user KPI refresh rate overrides

Revision ID: 4d8b2e1a9f6c
Revises: 9a1e2f6c7b3d
Create Date: 2026-07-22 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4d8b2e1a9f6c'
down_revision: Union[str, Sequence[str], None] = '9a1e2f6c7b3d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'user_kpi_refresh_rates',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('task', sa.String(length=50), nullable=False),
        sa.Column('interval_seconds', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'task'),
    )
    op.create_index(op.f('ix_user_kpi_refresh_rates_user_id'), 'user_kpi_refresh_rates', ['user_id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_user_kpi_refresh_rates_user_id'), table_name='user_kpi_refresh_rates')
    op.drop_table('user_kpi_refresh_rates')
