"""Add short_name to Feed model

Revision ID: ef1b121b0d0f
Revises: 001
Create Date: 2025-03-02 02:36:05.580758

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = 'ef1b121b0d0f'
down_revision = '001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Use batch operations for SQLite
    with op.batch_alter_table('feed') as batch_op:
        batch_op.add_column(sa.Column('short_name', sa.String(length=100), nullable=False))
        batch_op.create_index('ix_feed_short_name', ['short_name'], unique=True)


def downgrade() -> None:
    # Use batch operations for SQLite
    with op.batch_alter_table('feed') as batch_op:
        batch_op.drop_index('ix_feed_short_name')
        batch_op.drop_column('short_name')
