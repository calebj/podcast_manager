"""Base classes for SQLAlchemy models."""

from __future__ import annotations

from typing import Any

from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.ext.declarative import declared_attr
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Naming convention for constraints
convention: dict[str, str] = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(AsyncAttrs, DeclarativeBase):
    """Base class for all SQLAlchemy models."""

    metadata = MetaData(naming_convention=convention)

    @declared_attr.directive
    def __tablename__(cls) -> str:
        """Generate tablename from class name."""
        return cls.__name__.lower()

    id: Mapped[int] = mapped_column(primary_key=True)

    def to_dict(self) -> dict[str, Any]:
        """Convert model to dictionary."""
        return {c.key: getattr(self, c.key) for c in self.__table__.columns}
