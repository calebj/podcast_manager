"""Feed model for podcast RSS feeds."""

from __future__ import annotations

import re
from datetime import datetime  # noqa: TC003
from typing import TYPE_CHECKING

from sqlalchemy import String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base

if TYPE_CHECKING:
    from .episode import Episode


def generate_short_name(title: str) -> str:
    """Generate a short name (slug) from a title.

    Args:
        title: The title to convert to a short name

    Returns:
        str: A slug-like short name
    """
    # Convert to lowercase
    slug = title.lower()

    # Replace special characters with spaces
    slug = re.sub(r'[^\w\s]', ' ', slug)

    # Replace multiple spaces with a single space
    slug = re.sub(r'\s+', ' ', slug)

    # Strip leading/trailing spaces and replace internal spaces with underscores
    slug = slug.strip().replace(' ', '_')

    # Limit to 100 characters
    return slug[:100]


class Feed(Base):
    """Model representing a podcast RSS feed."""
    __table_args__ = (
        UniqueConstraint("url", name="uq_feed_url"),
    )

    # Feed metadata
    url: Mapped[str] = mapped_column(String(2048), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    short_name: Mapped[str | None] = mapped_column(String(100), unique=True, nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    language: Mapped[str | None] = mapped_column(String(50), nullable=True)
    author: Mapped[str | None] = mapped_column(String(512), nullable=True)
    image_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    website_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)

    # Feed update tracking
    last_fetched: Mapped[datetime | None] = mapped_column(nullable=True)
    last_updated: Mapped[datetime | None] = mapped_column(nullable=True)

    # Feed status
    auto_refresh: Mapped[bool] = mapped_column(default=True)
    episode_regex: Mapped[str | None] = mapped_column(String(500), nullable=True)
    download_path: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        default=func.now(), onupdate=func.now(),
    )

    # Relationships
    episodes: Mapped[list[Episode]] = relationship(
        back_populates="feed", cascade="all, delete-orphan",
    )

    def generate_short_name(self) -> str:
        """Generate a short name from the feed title."""
        return generate_short_name(self.title)

    def __repr__(self) -> str:
        """String representation of Feed."""
        short_name_str = f", short_name='{self.short_name}'" if self.short_name else ""
        return f"<Feed(id={self.id}, title='{self.title}'{short_name_str})>"
