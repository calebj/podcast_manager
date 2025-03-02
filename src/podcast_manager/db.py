"""Database connection and session management."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager, contextmanager
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy import URL, Engine, create_engine, event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session, sessionmaker

from .models import Base

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Generator


class DatabaseConfig:
    """Database configuration class."""

    def __init__(
        self,
        dialect: str = "sqlite",
        username: str | None = None,
        password: str | None = None,
        host: str | None = None,
        port: int | None = None,
        database: str = "podcast_manager.db",
    ):
        """Initialize database configuration.

        Args:
            dialect: Database dialect (sqlite, postgresql)
            username: Database username
            password: Database password
            host: Database host
            port: Database port
            database: Database name
        """
        self.dialect = dialect
        self.username = username
        self.password = password
        self.host = host
        self.port = port
        self.database = database

    def get_url(self, is_async: bool = False) -> URL:
        """Get database URL.

        Returns:
            URL: Database URL
        """
        driver = "pysqlite" if self.dialect == "sqlite" else None

        if self.dialect == "sqlite":
            if is_async:
                driver = "aiosqlite"

            return URL.create(
                drivername=f"{self.dialect}+{driver}" if driver else self.dialect,
                database=self.database,
            )
        else:
            raise NotImplementedError

        # PostgreSQL connection
        # if self.async_mode:
        #     driver = "asyncpg"
        #
        # return URL.create(
        #     drivername=f"{self.dialect}+{driver}" if driver else self.dialect,
        #     username=self.username,
        #     password=self.password,
        #     host=self.host,
        #     port=self.port,
        #     database=self.database,
        # )


class Database:
    """Database class for managing connections and sessions."""

    config: DatabaseConfig
    engine: Engine
    async_engine: AsyncEngine
    session_factory: sessionmaker[Session]
    async_session_factory: async_sessionmaker[AsyncSession]

    @staticmethod
    def _set_sqlite_pragma(
            dbapi_connection: sa.engine.interfaces.DBAPIConnection,
            connection_record: sa.pool.ConnectionPoolEntry,  # noqa: ARG004
    ) -> None:
        """Set SQLite PRAGMA options for each connection.

        Enables foreign key constraints enforcement in SQLite.
        """
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    def __init__(self, config: DatabaseConfig | None = None):
        """Initialize database.

        Args:
            config: Database configuration
        """
        self.config = config or DatabaseConfig()
        self.engine = None  # type: ignore[assignment]
        self.async_engine = None  # type: ignore[assignment]
        self.session_factory = None  # type: ignore[assignment]
        self.async_session_factory = None  # type: ignore[assignment]

    def init_sync_engine(self) -> None:
        """Initialize synchronous SQLAlchemy engine."""
        if self.engine:
            return

        connect_args: dict[str, str | bool] = {}
        if self.config.dialect == "sqlite":
            connect_args["check_same_thread"] = False
            # We'll set foreign keys via event listener for more reliability

        self.engine = create_engine(
            self.config.get_url(),
            echo=False,
            future=True,
            connect_args=connect_args,
        )

        # Enable foreign key constraints for SQLite
        if self.config.dialect == "sqlite":
            event.listen(self.engine, "connect", self._set_sqlite_pragma)

        self.session_factory = sessionmaker(
            bind=self.engine,
            autocommit=False,
            autoflush=False,
            expire_on_commit=False,
        )

    def init_async_engine(self) -> None:
        """Initialize asynchronous SQLAlchemy engine."""
        if self.async_engine:
            return

        connect_args: dict[str, str | bool] = {}
        if self.config.dialect == "sqlite":
            connect_args["check_same_thread"] = False

        self.async_engine = create_async_engine(
            self.config.get_url(is_async=True),
            echo=False,
            future=True,
            connect_args=connect_args,
        )

        # Enable foreign key constraints for SQLite
        if self.config.dialect == "sqlite":
            event.listen(self.async_engine.sync_engine, "connect", self._set_sqlite_pragma)

        self.async_session_factory = async_sessionmaker(
            bind=self.async_engine,
            autocommit=False,
            autoflush=False,
            expire_on_commit=False,
        )

    def create_tables(self) -> None:
        """Create all tables."""
        self.init_sync_engine()
        Base.metadata.create_all(self.engine)

    def drop_tables(self) -> None:
        """Drop all tables."""
        self.init_sync_engine()
        Base.metadata.drop_all(self.engine)

    def get_session(self) -> Session:
        """Get a new database session.

        Returns:
            Session: Database session
        """
        self.init_sync_engine()
        return self.session_factory()

    @contextmanager
    def session(self) -> Generator[Session, None, None]:
        """Get a database session as a context manager.

        Yields:
            Session: Database session
        """
        self.init_sync_engine()
        session = self.session_factory()
        try:
            yield session
        finally:
            session.close()

    @asynccontextmanager
    async def async_session(self) -> AsyncGenerator[AsyncSession, None]:
        """Get an async database session as a context manager.

        Yields:
            AsyncSession: Async database session
        """
        self.init_async_engine()
        async with self.async_session_factory() as session:
            try:
                yield session
            finally:
                await session.close()


# Create default database instance
db = Database(
    DatabaseConfig(
        dialect=os.environ.get("DB_DIALECT", "sqlite"),
        username=os.environ.get("DB_USERNAME"),
        password=os.environ.get("DB_PASSWORD"),
        host=os.environ.get("DB_HOST"),
        port=int(os.environ["DB_PORT"]) if os.environ.get("DB_PORT") else None,
        database=os.environ.get("DB_DATABASE", "podcast_manager.db"),
    ),
)
