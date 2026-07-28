"""per-user allowed KPIs (dashboard metric access)

Revision ID: 5e9c1a7b3f42
Revises: 4d8b2e1a9f6c
Create Date: 2026-07-23 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5e9c1a7b3f42'
down_revision: Union[str, Sequence[str], None] = '4d8b2e1a9f6c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # server_default '[]' backfills existing rows (= no restriction, all KPIs
    # visible); the ORM default handles new rows.
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('allowed_kpis', sa.JSON(), nullable=False, server_default='[]'))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('allowed_kpis')
