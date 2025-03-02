"""Add episode_regex and auto_refresh to Feed model

Revision ID: 82774cae0fa8
Revises: ef1b121b0d0f
Create Date: 2025-03-02 03:36:46.758318

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = '82774cae0fa8'
down_revision = 'ef1b121b0d0f'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Use batch operations for SQLite
    with op.batch_alter_table('feed') as batch_op:
        batch_op.add_column(sa.Column('auto_refresh', sa.Boolean(), nullable=False, server_default='1'))
        batch_op.add_column(sa.Column('episode_regex', sa.String(length=500), nullable=True))
    # ### end Alembic commands ###


def downgrade() -> None:
    # Use batch operations for SQLite
    with op.batch_alter_table('feed') as batch_op:
        batch_op.drop_column('episode_regex')
        batch_op.drop_column('auto_refresh')
    # ### end Alembic commands ###
