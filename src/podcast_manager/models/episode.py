"""Episode model for podcast episodes."""
from __future__ import annotations

from datetime import datetime  # noqa: TC003
from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base

if TYPE_CHECKING:
    from .feed import Feed
    from .segment import AdSegment


class DownloadStatus(str, Enum):
    """Status of episode download."""

    PENDING = "pending"
    DOWNLOADING = "downloading"
    DOWNLOADED = "downloaded"
    PROCESSED = "processed"
    FAILED = "failed"


class Episode(Base):
    """Model representing a podcast episode."""
    __table_args__ = (
        UniqueConstraint("guid", name="uq_episode_guid"),
    )

    # Episode metadata
    guid: Mapped[str] = mapped_column(String(2048), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_date: Mapped[datetime | None] = mapped_column(nullable=True)
    duration: Mapped[int | None] = mapped_column(Integer, nullable=True)  # in seconds

    # Media information
    media_url: Mapped[str] = mapped_column(String(2048))
    clean_media_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    media_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    media_size: Mapped[int | None] = mapped_column(Integer, nullable=True)  # in bytes

    # Download information
    # Just the filename relative to the feed's folder, not a full path
    download_filename: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    download_status: Mapped[str] = mapped_column(
        String(20), default=DownloadStatus.PENDING.value,
    )
    download_date: Mapped[datetime | None] = mapped_column(nullable=True)

    # Processing information
    processed_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    processed_date: Mapped[datetime | None] = mapped_column(nullable=True)
    original_duration: Mapped[int | None] = mapped_column(Integer, nullable=True)  # in seconds
    processed_duration: Mapped[int | None] = mapped_column(Integer, nullable=True)  # in seconds

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        default=func.now(), onupdate=func.now(),
    )

    # Relationships
    feed_id: Mapped[int] = mapped_column(ForeignKey("feed.id"))
    feed: Mapped[Feed] = relationship(back_populates="episodes")

    ad_segments: Mapped[list[AdSegment]] = relationship(
        back_populates="episode", cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        """String representation of Episode."""
        return f"<Episode(id={self.id}, title='{self.title}')>"
