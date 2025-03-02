"""Parser for podcast-dl folder structures."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import orjson
from sqlalchemy import select

from ..models import Episode, Feed
from ..models.feed import generate_short_name

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class PodcastDLParser:
    """Parser for podcast-dl folder structure.

    This parser imports feeds and episodes from a podcast-dl folder structure.
    It does not make any web requests, only reads metadata from disk.
    """

    def __init__(self, session: Session):
        """Initialize parser.

        Args:
            session: Database session
        """
        self.session = session

    def import_folder(
            self, folder_path: Path, rel_path: Path, short_name: str | None = None,
    ) -> Feed | None:
        """Import a podcast-dl folder.

        This method creates a new feed and imports all episodes from a podcast-dl folder.

        Args:
            folder_path: Path to folder containing podcast-dl metadata
            rel_path: The Path relative to the download base to store in the database
            short_name: Override for short_name (default is derived from feed title)

        Returns:
            Optional[Feed]: Imported feed or None if import failed
        """
        if not folder_path.exists() or not folder_path.is_dir():
            logger.error("Folder does not exist: %s", folder_path)
            return None

        # Scan folder metadata in a single pass
        (feed_metadata, feed_file), episode_files = self._scan_folder_metadata(folder_path)

        if not feed_metadata:
            logger.error("No feed metadata found in folder: %s", folder_path)
            return None

        # Create feed in database
        feed = self._create_feed(feed_metadata, rel_path, short_name=short_name)
        if not feed:
            return None

        # Process episodes
        imported_count = self._process_episodes_from_list(episode_files, feed, feed_file)

        logger.info("Imported %d episodes from %s", imported_count, folder_path)

        return feed

    def refresh_feed(self, feed: Feed, folder_path: str | Path) -> tuple[int, int]:
        """Refresh a feed from a podcast-dl folder.

        This method updates an existing feed with new episodes found in a podcast-dl folder.
        It also updates existing episodes with download paths if they're found in the folder.

        Args:
            feed: Existing feed to refresh
            folder_path: Path to folder containing podcast-dl metadata

        Returns:
            Tuple[int, int]: (new_episodes_count, updated_episodes_count)
        """
        folder_path = Path(folder_path)

        if not folder_path.exists() or not folder_path.is_dir():
            logger.error("Folder does not exist: %s", folder_path)
            return 0, 0

        # Scan folder metadata in a single pass
        (_, feed_file), episode_files = self._scan_folder_metadata(folder_path)

        # Get all existing episodes for this feed in a single query using SQLAlchemy 2.0 style
        # Build a dictionary mapping GUIDs to episode objects for efficient lookup
        stmt = select(Episode).where(Episode.feed_id == feed.id)
        result = self.session.execute(stmt)

        existing_episodes = {episode.guid: episode for episode in result.scalars().all()}

        # Process all episode files in the folder
        new_count = 0
        updated_count = 0

        for episode_file in episode_files:
            # Skip the feed metadata file
            if feed_file and episode_file == feed_file:
                continue

            # Process episode
            try:
                # Read episode metadata
                with episode_file.open("rb") as f:
                    metadata = orjson.loads(f.read())

                # Extract GUID
                guid = metadata.get("guid")
                if not guid:
                    logger.warning("Episode metadata does not contain guid: %s", episode_file)
                    continue

                # Check if episode already exists using our dictionary
                if guid in existing_episodes:
                    # Get the existing episode from our dictionary
                    existing_episode = existing_episodes[guid]

                    # If the episode exists but is not downloaded, update it
                    if existing_episode.download_filename is None or existing_episode.download_status != "downloaded":
                        # Look for media file
                        media_path = self._find_media_file(episode_file)
                        if media_path:
                            # Always use relative paths
                            if not media_path.is_relative_to(folder_path):
                                raise ValueError(f"Media file {media_path} is not within the folder {folder_path}")

                            # Get the filename relative to the feed's folder
                            existing_episode.download_filename = str(media_path.relative_to(folder_path))
                            existing_episode.download_status = "downloaded"
                            existing_episode.download_date = datetime.now(UTC)

                            # Also update duration if not set and available in metadata
                            if existing_episode.duration is None and "duration" in metadata.get("itunes", {}):
                                duration_str = metadata["itunes"]["duration"]
                                duration = self._parse_duration(duration_str)
                                if duration:
                                    existing_episode.duration = duration

                            self.session.commit()
                            updated_count += 1
                            logger.info("Updated existing episode: %s", existing_episode.title)
                else:
                    # Import new episode
                    new_episode = self._import_episode(episode_file, feed)
                    if new_episode:
                        new_count += 1
                        # Add the new episode to our dictionary to avoid duplicates if multiple files have same guid
                        existing_episodes[new_episode.guid] = new_episode

            except (OSError, json.JSONDecodeError) as e:
                logger.warning("Failed to read episode metadata file %s: %s", episode_file, e)
                continue

        return new_count, updated_count

    def _process_episodes_from_list(self, episode_files: list[Path], feed: Feed, feed_file: Path | None) -> int:
        """Process a list of episode metadata files.

        Args:
            episode_files: List of episode metadata files
            feed: Feed to associate episodes with
            feed_file: Path to feed metadata file (to skip)

        Returns:
            int: Number of imported episodes
        """
        # Import episodes
        imported_count = 0
        for episode_file in episode_files:
            # Skip the feed metadata file
            if feed_file and episode_file == feed_file:
                continue

            # Import episode
            episode = self._import_episode(episode_file, feed)
            if episode:
                imported_count += 1

        return imported_count

    def _scan_folder_metadata(self, folder_path: Path) -> tuple[tuple[dict[str, Any] | None, Path | None], list[Path]]:
        """Scan a folder for podcast-dl metadata files in a single pass.

        This function scans all *.meta.json files in the folder, identifies the feed metadata file
        and returns the feed metadata along with a list of all episode metadata files.
        Files are sorted by modification time (oldest first) to ensure consistent processing.

        Args:
            folder_path: Path to folder containing podcast-dl metadata

        Returns:
            Tuple containing:
            - Tuple[Optional[Dict], Optional[Path]]: Feed metadata and file path, or (None, None) if not found
            - List[Path]: All episode metadata files (excluding the feed file)
        """
        # Find all .meta.json files and sort by modification time (oldest first)
        meta_files = sorted(
            folder_path.glob("*.meta.json"),
            key=lambda p: p.stat().st_mtime,
        )

        feed_metadata = None
        feed_file = None
        episode_files = []
        continue_offset = 0

        # Process all meta files in a single pass
        for i, meta_file in enumerate(meta_files):
            try:
                with Path(meta_file).open("rb") as f:
                    metadata = orjson.loads(f.read())

                # Check if this is a feed metadata file (has feedUrl)
                if "feedUrl" in metadata:
                    feed_metadata = metadata
                    feed_file = meta_file
                    continue_offset = i + 1
                    break
                else:
                    # Add to episode files list
                    episode_files.append(meta_file)
            except (OSError, json.JSONDecodeError) as e:
                logger.warning("Failed to read metadata file %s: %s", meta_file, e)
                # Add to episode files anyway, so the calling code can handle the error
                episode_files.append(meta_file)

        episode_files.extend(meta_files[continue_offset:])

        return (feed_metadata, feed_file), episode_files

    def _create_feed(
            self, metadata: dict[str, Any], rel_path: Path, short_name: str | None = None,
    ) -> Feed | None:
        """Create a feed from podcast-dl metadata.

        Args:
            metadata: Feed metadata from podcast-dl
            short_name: Override value for short_name

        Returns:
            Optional[Feed]: Created feed or None if creation failed
        """
        # Check if feed already exists
        feed_url = metadata.get("feedUrl")
        if not feed_url:
            logger.error("Feed metadata does not contain feedUrl")
            return None

        existing_feed = self.session.query(Feed).filter(Feed.url == feed_url).first()
        if existing_feed:
            logger.info("Feed already exists: %s", existing_feed.title)
            return existing_feed

        if short_name is None:
            short_name = generate_short_name(metadata["title"])

        conflict_feed = self.session.query(Feed).filter(Feed.short_name == short_name).first()
        if conflict_feed:
            logger.error(
                "Feed with shortname '%s' exists with another feed URL: %s",
                conflict_feed.short_name, conflict_feed.title,
            )
            return None

        # Parse build date if present
        last_fetched = None
        build_date = metadata.get("lastBuildDate")
        if build_date:
            try:
                # Parse the date string and then make it timezone-aware
                # DTZ007 is expected here since %Z doesn't set tzinfo, but we manually set it after
                parsed_date = datetime.strptime(build_date, "%a, %d %b %Y %H:%M:%S %Z")  # noqa: DTZ007
                last_fetched = parsed_date.replace(tzinfo=UTC)
            except ValueError:
                logger.warning("Failed to parse lastBuildDate: %s", build_date)

        # Extract image URL
        image_url = None
        if "image" in metadata and "url" in metadata["image"]:
            image_url = metadata["image"]["url"]
        elif "itunes" in metadata and "image" in metadata["itunes"]:
            image_url = metadata["itunes"]["image"]

        # Create feed
        feed = Feed(
            url=feed_url,
            title=metadata["title"],
            description=metadata.get("description"),
            language=metadata.get("language"),
            author=metadata.get("author") or metadata.get("creator"),
            image_url=image_url,
            website_url=metadata.get("link"),
            short_name=short_name,
            download_path=str(rel_path),
            last_fetched=last_fetched,
            auto_refresh=True,
        )

        self.session.add(feed)
        self.session.commit()

        logger.info("Created feed: %s", feed.title)
        return feed

    def _import_episode(self, episode_file: Path, feed: Feed) -> Episode | None:
        """Import an episode from podcast-dl metadata.

        Args:
            episode_file: Path to episode metadata file
            feed: Feed to associate episode with

        Returns:
            Optional[Episode]: Imported episode or None if import failed
        """
        try:
            with Path(episode_file).open("rb") as f:
                metadata = orjson.loads(f.read())
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("Failed to read episode metadata file %s: %s", episode_file, e)
            return None

        # Extract GUID
        guid = metadata.get("guid")
        if not guid:
            logger.warning("Episode metadata does not contain guid: %s", episode_file)
            return None

        # Check if episode already exists
        existing_episode = self.session.query(Episode).filter(Episode.guid == guid).first()
        if existing_episode:
            logger.info("Episode already exists: %s (guid %s)", existing_episode.title, guid)
            return existing_episode

        # Extract media URL and information
        media_url = None
        media_type = None
        media_size = None

        if "enclosure" in metadata:
            enclosure = metadata["enclosure"]
            media_url = enclosure.get("url")
            media_type = enclosure.get("type")

            # Convert media size to integer if present
            try:
                if enclosure.get("length"):
                    media_size = int(enclosure["length"])
            except (ValueError, TypeError):
                logger.warning("Failed to parse media size: %s", enclosure.get('length'))

        if not media_url:
            logger.warning("Episode does not have media URL: %s", episode_file)
            return None

        # Parse publication date
        published_date = None
        pub_date = metadata.get("pubDate") or metadata.get("isoDate")
        if pub_date:
            try:
                try:
                    try:
                        # Format with timezone offset (%z)
                        published_date = datetime.strptime(pub_date, "%a, %d %b %Y %H:%M:%S %z")
                    except ValueError:
                        # Format with timezone name (%Z) - make it timezone-aware with UTC
                        # DTZ007 is expected here since %Z doesn't set tzinfo, but we manually set it after
                        parsed_date = datetime.strptime(pub_date, "%a, %d %b %Y %H:%M:%S %Z")  # noqa: DTZ007
                        published_date = parsed_date.replace(tzinfo=UTC)
                except ValueError:
                    published_date = datetime.fromisoformat(pub_date.replace("Z", "+00:00"))
            except ValueError:
                logger.warning("Failed to parse publication date: %s", pub_date)

        # Extract duration in seconds
        duration = None
        if "itunes" in metadata and "duration" in metadata["itunes"]:
            duration_str = metadata["itunes"]["duration"]
            duration = self._parse_duration(duration_str)

        # Look for media file (same name as metadata file but without .meta.json)
        media_path = self._find_media_file(episode_file)

        # Create episode
        # If we have a media_path, always convert it to a path relative to the feed's download_path
        if media_path:
            # Store path relative to feed's download_path
            # First make it relative to the containing folder
            folder_path = episode_file.parent
            # The media file should always be in the same folder as its metadata
            if not media_path.is_relative_to(folder_path):
                raise ValueError(f"Media file {media_path} is not within the folder {folder_path}")

            # Get the path component relative to the folder - this becomes the filename
            filename = media_path.relative_to(folder_path)

        episode = Episode(
            feed=feed,
            guid=guid,
            title=metadata.get("title", ""),
            description=metadata.get("content") or metadata.get("contentSnippet") or "",
            published_date=published_date,
            duration=duration,
            media_url=media_url,
            media_type=media_type,
            media_size=media_size,
            download_filename=str(filename) if media_path else None,
            download_status="downloaded" if media_path else "pending",
            download_date=datetime.now(UTC) if media_path else None,
        )

        self.session.add(episode)
        self.session.commit()

        return episode

    def _find_media_file(self, metadata_file: Path) -> Path | None:
        """Find media file associated with a metadata file.

        Args:
            metadata_file: Path to metadata file

        Returns:
            Optional[Path]: Path to media file or None if not found
        """
        # Remove .meta.json from filename
        base_name = metadata_file.stem
        if base_name.endswith(".meta"):
            base_name = base_name[:-5]

        # Look for media files with common extensions
        for ext in [".mp3", ".m4a", ".ogg", ".wav", ".flac"]:
            media_file = metadata_file.parent / f"{base_name}{ext}"
            if media_file.exists():
                return media_file

        return None

    def _parse_duration(self, duration_str: str) -> int | None:
        """Parse duration string to seconds.

        Args:
            duration_str: Duration string (HH:MM:SS, MM:SS, or seconds)

        Returns:
            Optional[int]: Duration in seconds or None if parsing failed
        """
        try:
            # If it's just a number
            if duration_str.isdigit():
                return int(duration_str)

            # If it's a time format
            parts = duration_str.split(":")
            if len(parts) == 3:  # HH:MM:SS
                h, m, s = map(int, parts)
                return h * 3600 + m * 60 + s
            elif len(parts) == 2:  # MM:SS
                m, s = map(int, parts)
                return m * 60 + s

            return None
        except (ValueError, TypeError):
            return None
