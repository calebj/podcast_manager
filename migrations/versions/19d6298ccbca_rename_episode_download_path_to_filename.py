"""Rename Episode.download_path to Episode.download_filename and change to relative paths

Revision ID: 19d6298ccbca
Revises: 204fc5330c86
Create Date: 2025-03-02 18:56:48.668751

"""
from pathlib import Path

import sqlalchemy as sa
from alembic import op
from sqlalchemy.orm import Session

# revision identifiers, used by Alembic.
revision = '19d6298ccbca'
down_revision = '204fc5330c86'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create temporary column to hold the filename values
    op.add_column('episode', sa.Column('download_filename', sa.String(length=1024), nullable=True))

    # Get database connection
    connection = op.get_bind()
    session = Session(bind=connection)

    # Update download_filename with just the filename part (relative to feed folder)
    # Query all episodes with their corresponding feed download paths
    results = session.execute(sa.text(
        """
        SELECT e.id, e.download_path, f.download_path as feed_path
        FROM episode e
        JOIN feed f ON e.feed_id = f.id
        WHERE e.download_path IS NOT NULL
        """,
    )).fetchall()

    # Update download_filename with the correct values
    for episode_id, download_path, feed_path in results:
        if download_path and feed_path:
            try:
                # Check if download_path starts with feed_path
                if download_path.startswith(f"{feed_path}/"):
                    # Extract just the part after feed_path/
                    filename = download_path[len(feed_path) + 1:]
                else:
                    # Just use the filename if it doesn't follow the expected pattern
                    filename = Path(download_path).name

                session.execute(
                    sa.text("UPDATE episode SET download_filename = :filename WHERE id = :episode_id"),
                    {"filename": filename, "episode_id": episode_id},
                )
            except Exception as e:
                print(f"Error processing download_path '{download_path}' for episode {episode_id}: {e}")
                raise

    # Commit changes
    session.commit()

    # Drop the old column
    op.drop_column('episode', 'download_path')


def downgrade() -> None:
    # Add back the original column
    op.add_column('episode', sa.Column('download_path', sa.String(length=1024), nullable=True))

    # Get database connection
    connection = op.get_bind()
    session = Session(bind=connection)

    # Restore the original paths by joining feed download_path with episode download_filename
    results = session.execute(sa.text(
        """
        SELECT e.id, e.download_filename, f.download_path as feed_path
        FROM episode e
        JOIN feed f ON e.feed_id = f.id
        WHERE e.download_filename IS NOT NULL
        """,
    )).fetchall()

    # Update download_path with the full paths
    for result in results:
        episode_id, download_filename, feed_path = result

        if download_filename and feed_path:
            full_path = f"{feed_path}/{download_filename}"

            # Update the download_path column using parameterized query
            session.execute(
                sa.text("UPDATE episode SET download_path = :full_path WHERE id = :episode_id"),
                {"full_path": full_path, "episode_id": episode_id},
            )

    # Commit changes
    session.commit()

    # Drop the new column
    op.drop_column('episode', 'download_filename')
