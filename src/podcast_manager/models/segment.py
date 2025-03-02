"""Ad segment model for podcast episodes."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003
from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy import Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base

if TYPE_CHECKING:
    from .episode import Episode


class SegmentType(str, Enum):
    """Type of segment."""

    AD = "ad"
    INTRO = "intro"
    OUTRO = "outro"
    CONTENT = "content"
    MUSIC = "music"
    UNKNOWN = "unknown"


class SegmentStatus(str, Enum):
    """Status of segment identification."""

    PREDICTED = "predicted"
    VERIFIED = "verified"
    REJECTED = "rejected"


class AdSegment(Base):
    """Model representing an ad segment within a podcast episode."""

    # Segment time information (in milliseconds)
    start_time: Mapped[int] = mapped_column(Integer)
    end_time: Mapped[int] = mapped_column(Integer)

    # Segment information
    segment_type: Mapped[str] = mapped_column(
        String(20), default=SegmentType.AD.value,
    )
    status: Mapped[str] = mapped_column(
        String(20), default=SegmentStatus.PREDICTED.value,
    )
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Notes and metadata
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    transcript: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        default=func.now(), onupdate=func.now(),
    )

    # Relationships
    episode_id: Mapped[int] = mapped_column(ForeignKey("episode.id"))
    episode: Mapped[Episode] = relationship(back_populates="ad_segments")

    def __repr__(self) -> str:
        """String representation of AdSegment."""
        return (
            f"<AdSegment(id={self.id}, type={self.segment_type}, "
            f"time={self.start_time/1000:.1f}s-{self.end_time/1000:.1f}s)>"
        )

    @property
    def duration(self) -> int:
        """Get segment duration in milliseconds."""
        return self.end_time - self.start_time
