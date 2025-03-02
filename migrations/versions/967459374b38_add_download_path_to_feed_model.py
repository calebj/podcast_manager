"""Add download_path to Feed model

Revision ID: 967459374b38
Revises: 82774cae0fa8
Create Date: 2025-03-02 04:51:18.864582

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = '967459374b38'
down_revision = '82774cae0fa8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add download_path as nullable first
    with op.batch_alter_table('feed') as batch_op:
        batch_op.add_column(sa.Column('download_path', sa.String(length=500), nullable=True))

    # Update the download_path with the short_name for existing records
    conn = op.get_bind()
    conn.execute(sa.text("UPDATE feed SET download_path = short_name WHERE download_path IS NULL"))

    # Now alter the column to be non-nullable
    with op.batch_alter_table('feed') as batch_op:
        batch_op.alter_column('download_path', nullable=False, existing_type=sa.String(500))


def downgrade() -> None:
    # Simply drop the download_path column
    with op.batch_alter_table('feed') as batch_op:
        batch_op.drop_column('download_path')

