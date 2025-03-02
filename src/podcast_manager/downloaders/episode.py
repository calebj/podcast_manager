"""Downloader for podcast episodes."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import aiofiles
import aiohttp
import requests

from ..models import Episode, Feed
from ..models.episode import DownloadStatus
from ..parsers.url import clean_episode_url

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.orm import Session

    from ..db import Database

logger = logging.getLogger(__name__)


def _sanitize_filename(filename: str) -> str:
    """Sanitize filename.

    Args:
        filename: Original filename

    Returns:
        str: Sanitized filename
    """
    # Replace problematic characters
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        filename = filename.replace(char, "_")

    # Limit length
    if len(filename) > 240:
        filename = filename[:240]

    return filename


def _get_extension_from_media_type(media_type: str | None) -> str:
    """Get file extension from media type.

    Args:
        media_type: Media type (MIME type)

    Returns:
        str: File extension
    """
    if not media_type:
        return ".mp3"  # Default to mp3

    media_type = media_type.lower()

    if "mpeg" in media_type or "mp3" in media_type:
        return ".mp3"
    elif "mp4" in media_type or "m4a" in media_type:
        return ".m4a"
    elif "ogg" in media_type:
        return ".ogg"
    elif "wav" in media_type:
        return ".wav"
    elif "flac" in media_type:
        return ".flac"
    else:
        return ".mp3"  # Default to mp3


class EpisodeDownloader:
    """Downloader for podcast episodes."""

    def __init__(
        self,
        download_dir: str = "downloads",
    ):
        """Initialize downloader.

        Args:
            download_dir: Directory to store downloaded episodes
        """
        self.download_dir = Path(download_dir)

    def get_episode_full_path(self, episode: Episode) -> Path | None:
        """Get the full path to an episode's downloaded file.

        Constructs the full path by combining:
        - Base download directory
        - Feed download path
        - Episode filename

        Args:
            episode: Episode to get path for

        Returns:
            Path | None: Full path to the episode file or None if episode is not downloaded
        """
        if not episode.download_filename:
            return None

        return self.download_dir / episode.feed.download_path / episode.download_filename

    def download_episode(
        self,
        episode: Episode,
        session: Session,
        force: bool = False,
    ) -> tuple[bool, str | None]:
        """Download episode to local storage.

        Args:
            episode: Episode to download
            session: Database session
            force: Force download even if already downloaded

        Returns:
            Tuple[bool, Optional[str]]: (success, error_message)
        """
        if episode.download_status == DownloadStatus.DOWNLOADED.value and not force:
            logger.info("Episode already downloaded: %s", episode.title)
            return True, None

        if not episode.media_url:
            return False, "No media URL provided"

        try:
            # Update status to downloading
            episode.download_status = DownloadStatus.DOWNLOADING.value

            # Clean the URL and save it to the database
            if not episode.clean_media_url:
                episode.clean_media_url = self._clean_episode_url(episode.media_url)

            session.commit()

            # Generate download path
            filename = self._generate_download_filename(episode)
            download_path = self.download_dir / episode.feed.download_path / filename
            temp_path = download_path.with_suffix(download_path.suffix + ".part")

            # Download file using the clean URL
            logger.info("Downloading episode: %s to %s", episode.title, temp_path)
            self._download_file(episode.clean_media_url or episode.media_url, temp_path)
            temp_path.rename(download_path)

            # Update episode with just the filename (relative to feed's folder)
            # Get the part relative to the feed's folder
            episode.download_filename = str(filename)
            episode.download_status = DownloadStatus.DOWNLOADED.value
            episode.download_date = datetime.now(UTC)
            session.commit()

            return True, None
        except Exception as e:
            logger.exception("Failed to download episode %s", episode.title)
            episode.download_status = DownloadStatus.FAILED.value
            session.commit()
            return False, str(e)

    async def download_episode_async(
        self,
        feed: Feed,
        episode: Episode,
        session: AsyncSession,
        http_session: aiohttp.ClientSession,
        force: bool = False,
    ) -> tuple[bool, str | None]:
        """Download episode to local storage asynchronously.

        Args:
            feed: Feed to which the episode belongs
            episode: Episode to download
            session: Async database session
            http_session: aiohttp ClientSession
            force: Force download even if already downloaded

        Returns:
            Tuple[bool, Optional[str]]: (success, error_message)
        """
        if episode.download_status == DownloadStatus.DOWNLOADED.value and not force:
            logger.info("Episode already downloaded: %s", episode.title)
            return True, None

        if not episode.media_url:
            return False, "No media URL provided"

        try:
            # Update status to downloading
            episode.download_status = DownloadStatus.DOWNLOADING.value

            # Clean the URL and save it to the database
            if not episode.clean_media_url:
                episode.clean_media_url = self._clean_episode_url(episode.media_url)

            await session.commit()

            # Generate download path
            filename = self._generate_download_filename(episode)
            download_path = self.download_dir / feed.download_path / filename
            temp_path = download_path.with_suffix(download_path.suffix + ".part")

            # Download file using the clean URL
            logger.info("Downloading episode: %s to %s", episode.title, download_path)
            await self._async_download_file(episode.clean_media_url or episode.media_url, temp_path, http_session)
            temp_path.rename(download_path)

            # Update episode with just the filename (relative to feed's folder)
            # Get the part relative to the feed's folder
            episode.download_filename = str(filename)
            episode.download_status = DownloadStatus.DOWNLOADED.value
            episode.download_date = datetime.now(UTC)
            await session.commit()

            return True, None
        except Exception as e:
            logger.exception("Failed to download episode %s", episode.title)
            episode.download_status = DownloadStatus.FAILED.value
            await session.commit()
            return False, str(e)

    async def download_episodes_concurrent(
        self,
        episodes: list[Episode],
        db: Database,
        max_concurrent: int = 5,
        force: bool = False,
    ) -> list[tuple[Episode, bool, str | None]]:
        """Download multiple episodes concurrently.

        Args:
            episodes: List of episodes to download
            db: Database instance
            max_concurrent: Maximum number of concurrent downloads
            force: Force download even if already downloaded

        Returns:
            List of tuples (episode, success, error_message)
        """
        results: list[tuple[Episode, bool, str | None]] = []

        # Set up semaphore to limit concurrent downloads
        semaphore = asyncio.Semaphore(max_concurrent)

        async def download_with_semaphore(episode: Episode) -> tuple[Episode, bool, str | None]:
            # Create a fresh session for each download
            async with semaphore, db.async_session() as session:
                # Refresh the episode object with the new session
                refreshed_episode = await session.get(Episode, episode.id)
                if not refreshed_episode:
                    return episode, False, "Episode not found in database"

                feed = await refreshed_episode.awaitable_attrs.feed

                # Use a dedicated HTTP session for each download
                async with aiohttp.ClientSession() as http_session:
                    success, error = await self.download_episode_async(
                        feed, refreshed_episode, session, http_session, force,
                    )
                    return refreshed_episode, success, error

        # Create download tasks
        tasks = [download_with_semaphore(episode) for episode in episodes]

        # Run all tasks concurrently
        results = await asyncio.gather(*tasks)

        return results

    def _generate_download_filename(self, episode: Episode) -> str:
        """Generate download path for episode.

        Args:
            episode: Episode

        Returns:
            Path: Download path
        """

        # Generate filename
        # First try to use published date
        if episode.published_date:
            # YYYYMMDD to follow podcast-dl format
            date_str = episode.published_date.strftime("%Y%m%d")
            filename = f"{date_str} {_sanitize_filename(episode.title)}"
        else:
            filename = _sanitize_filename(episode.title)

        # Add extension based on media type
        extension = _get_extension_from_media_type(episode.media_type)
        if not filename.endswith(extension):
            filename = f"{filename}{extension}"

        return filename

    def _clean_episode_url(self, url: str) -> str:
        return clean_episode_url(url)

    def _download_file(self, url: str, path: Path) -> None:
        """Download file from URL to path.

        Args:
            url: URL to download from (should already be cleaned)
            path: Path to save to
        """
        with requests.get(url, stream=True, timeout=60) as r:
            r.raise_for_status()
            path.parent.mkdir(parents=True, exist_ok=True)

            with path.open("wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)

    async def _async_download_file(self, url: str, path: Path, session: aiohttp.ClientSession) -> None:
        """Download file from URL to path asynchronously.

        Args:
            url: URL to download from (should already be cleaned)
            path: Path to save to
            session: aiohttp ClientSession
        """
        path.parent.mkdir(parents=True, exist_ok=True)

        async with session.get(url, timeout=aiohttp.ClientTimeout(60)) as response:
            response.raise_for_status()

            async with aiofiles.open(path, "wb") as f:
                async for chunk in response.content.iter_chunked(8192):
                    await f.write(chunk)
