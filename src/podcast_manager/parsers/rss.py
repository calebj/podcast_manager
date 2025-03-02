"""RSS feed parser for podcasts."""

from __future__ import annotations

import datetime
import logging
from typing import TYPE_CHECKING

import feedparser  # type: ignore[import-untyped]
import requests

from ..models import Episode, Feed
from ..models.feed import generate_short_name

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class RSSParser:
    """Parser for RSS feeds."""

    def __init__(self, session: Session):
        """Initialize parser.

        Args:
            session: Database session
        """
        self.session = session

    def fetch_feed(self, url: str) -> feedparser.FeedParserDict | None:
        """Fetch RSS feed from URL.

        Args:
            url: RSS feed URL

        Returns:
            Optional[feedparser.FeedParserDict]: Parsed feed, or None if fetching failed
        """
        try:
            logger.info("Fetching RSS feed: %s", url)
            response = requests.get(
                url,
                timeout=30,
                headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:135.0) Gecko/20100101 Firefox/135.0"},
            )
            response.raise_for_status()
            return feedparser.parse(response.content)
        except (requests.RequestException, Exception):
            logger.exception("Failed to fetch feed %s", url)
            return None

    def parse_feed(
        self,
        url: str,
        short_name: str | None = None,
        episode_regex: str | None = None,
        download_path: str | None = None,
        auto_refresh: bool | None = None,
        skip_episode_parsing: bool | None = False,
    ) -> Feed | None:
        """Parse RSS feed and store in database.

        Args:
            url: RSS feed URL
            short_name: Optional short name for the feed
            episode_regex: Optional regex to filter episode titles
            download_path: Optional custom download path for episodes
            auto_refresh: Optional flag to control automatic refresh (None = don't change)
            skip_episode_parsing: Refresh feed metadata without updating episodes

        Returns:
            Optional[Feed]: Feed object if successful, None otherwise
        """
        feed_data = self.fetch_feed(url)
        if not feed_data:
            return None

        # Check if feed already exists
        feed = self.session.query(Feed).filter(Feed.url == url).first()

        if not feed:
            # First determine the short name
            feed_short_name = short_name if short_name else generate_short_name(feed_data.feed["title"])

            # Then determine the download path (defaulting to short_name if not provided)
            feed_download_path = download_path if download_path else feed_short_name

            # Create new feed
            feed = Feed(
                url=url,
                title=feed_data.feed["title"],
                description=feed_data.feed.get("description") or feed_data.feed.get("subtitle"),
                language=feed_data.feed.get("language"),
                author=feed_data.feed.get("author") or self._get_author(feed_data),
                image_url=self._get_image_url(feed_data),
                website_url=feed_data.feed.get("link"),
                short_name=feed_short_name,
                download_path=feed_download_path,
                episode_regex=episode_regex,
                auto_refresh=True if auto_refresh is None else auto_refresh,
            )
            self.session.add(feed)
        else:
            # Update existing feed
            feed.title = feed_data.feed.get("title", feed.title)
            feed.description = feed_data.feed.get("description") or feed_data.feed.get("subtitle") or feed.description
            feed.language = feed_data.feed.get("language", feed.language)
            feed.author = feed_data.feed.get("author") or self._get_author(feed_data) or feed.author
            feed.image_url = self._get_image_url(feed_data) or feed.image_url
            feed.website_url = feed_data.feed.get("link", feed.website_url)

            # Update configuration if provided
            if short_name:
                feed.short_name = short_name
            if download_path:
                feed.download_path = download_path
            if episode_regex is not None:
                feed.episode_regex = episode_regex
            if auto_refresh is not None:
                feed.auto_refresh = auto_refresh

        feed.last_fetched = datetime.datetime.now(datetime.UTC)
        self.session.commit()

        if not skip_episode_parsing:
            # Parse episodes, tracking GUIDs to handle duplicates
            processed_guids = set()
            for entry in reversed(feed_data.entries):
                # Extract the GUID
                guid = entry.get("id") or entry.get("guid")
                if not guid:
                    logger.warning("No guid found for entry, skipping: %s", entry.get("title"))
                    continue

                if guid in processed_guids:
                    # This is a duplicate GUID
                    logger.warning(
                        "Duplicate GUID found in feed '%s': %s (title: %s) - skipping",
                        feed.title,
                        guid,
                        entry.get("title"),
                    )
                    continue

                # Add GUID to the set of processed GUIDs
                processed_guids.add(guid)

                # Process the episode
                self.parse_episode(feed, entry)

            self.session.commit()

        return feed

    def parse_episode(self, feed: Feed, entry: dict) -> Episode | None:
        """Parse episode from feed entry.

        Args:
            feed: Feed object
            entry: Feed entry

        Returns:
            Optional[Episode]: Episode object if successful, None otherwise
        """
        guid = entry.get("id") or entry.get("guid")
        # Note: We don't need to check for missing GUID here anymore
        # as that's handled in the parse_feed method

        # Ensure title exists
        if not entry.get("title"):
            logger.warning("No title found for entry with guid %s, skipping", guid)
            return None

        # Check if episode already exists
        episode = self.session.query(Episode).filter(Episode.guid == guid).first()
        if episode:
            return episode

        # Find enclosure (media file)
        enclosure = self._get_enclosure(entry)
        if not enclosure:
            logger.warning("No media enclosure found for entry: %s", entry.get("title", "Unknown"))
            return None

        media_url = enclosure.get("href") or enclosure.get("url", "")
        if not media_url:
            logger.warning("No media URL found for entry: %s", entry.get("title", "Unknown"))
            return None

        # Parse publication date
        published_date = self._parse_date(entry)

        media_size = None if enclosure.get("length") == '' else int(enclosure.get("length", 0)) or None

        # Create episode
        episode = Episode(
            feed=feed,
            guid=guid,
            title=entry["title"].strip(),
            description=entry.get("description") or entry.get("summary") or entry.get("subtitle", ""),
            published_date=published_date,
            duration=self._parse_duration(entry),
            media_url=media_url,
            media_type=enclosure.get("type", "audio/mpeg"),
            media_size=media_size,
        )

        self.session.add(episode)
        return episode

    def _get_author(self, feed_data: feedparser.FeedParserDict) -> str:
        """Extract author from feed data.

        Args:
            feed_data: Feed data

        Returns:
            str: Author name or empty string
        """
        if "author_detail" in feed_data.feed:
            return feed_data.feed.author_detail.get("name", "")

        # Try to get from iTunes tags
        for key in feed_data.feed:
            if "itunes_author" in key:
                return feed_data.feed[key]

        return ""

    def _get_image_url(self, feed_data: feedparser.FeedParserDict) -> str | None:
        """Extract image URL from feed data.

        Args:
            feed_data: Feed data

        Returns:
            Optional[str]: Image URL or None
        """
        # Try standard image
        if "image" in feed_data.feed and "href" in feed_data.feed.image:
            return feed_data.feed.image.href

        # Try iTunes image
        for key in feed_data.feed:
            if "itunes_image" in key and "href" in feed_data.feed[key]:
                return feed_data.feed[key].href

        return None

    def _get_enclosure(self, entry: dict) -> dict | None:
        """Get media enclosure from entry.

        Args:
            entry: Feed entry

        Returns:
            Optional[dict]: Enclosure data or None
        """
        if "enclosures" in entry and entry.enclosures:
            for enclosure in entry.enclosures:
                # Prefer audio files
                if enclosure.get("type", "").startswith("audio/"):
                    return enclosure
            # If no audio files, return the first enclosure
            return entry.enclosures[0]

        return None

    def _parse_date(self, entry: dict) -> datetime.datetime | None:
        """Parse publication date from entry.

        Args:
            entry: Feed entry

        Returns:
            Optional[datetime.datetime]: Publication date or None
        """
        for key in ["published_parsed", "updated_parsed", "created_parsed"]:
            if entry.get(key):
                try:
                    # Create timezone-aware datetime with UTC timezone
                    # suppress mypy warning since tuple from feedparser _parsed timezone is always in UTC
                    return datetime.datetime(*entry[key][:6], tzinfo=datetime.UTC)  # type: ignore[misc]
                except (ValueError, TypeError):
                    pass

        return None

    def _parse_duration(self, entry: dict) -> int | None:
        """Parse duration from entry.

        Args:
            entry: Feed entry

        Returns:
            Optional[int]: Duration in seconds or None
        """
        # Try to get from iTunes duration
        for key, value in entry.items():
            if "itunes_duration" in key:
                return self._convert_duration_to_seconds(value)

        return None

    def _convert_duration_to_seconds(self, duration_str: str) -> int | None:
        """Convert duration string to seconds.

        Args:
            duration_str: Duration string (HH:MM:SS, MM:SS, or seconds)

        Returns:
            Optional[int]: Duration in seconds or None
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
