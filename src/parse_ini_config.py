#!/usr/bin/env python3
r"""
Script to import podcast feeds from an INI-format file.

Format example:
[my_podcast]
url = https://example.com/feed.xml
regex = ^Episode \d+:  # Optional: Only download episodes matching this regex
outdir = my_podcast/special  # Optional: Custom download path (defaults to short_name)

[another_podcast]
url = https://another-example.com/rss
"""

import argparse
import configparser
import logging
import sys

from sqlalchemy.exc import IntegrityError

from podcast_manager.db import db
from podcast_manager.models import Feed
from podcast_manager.parsers import RSSParser

log = logging.getLogger(__name__)


def parse_ini_file(file_path: str) -> dict[str, dict[str, str]]:
    """Parse the INI file and extract the feed configuration.

    Args:
        file_path: Path to the INI file

    Returns:
        Dictionary mapping short names to feed configs
    """
    config = configparser.ConfigParser(interpolation=configparser.ExtendedInterpolation(), delimiters=('=',))
    config.read(file_path)

    feeds = {}
    for section in config.sections():
        short_name = section
        if 'url' not in config[section]:
            logging.warning("Section '%s' does not have a 'url' key, skipping", section)
            continue

        # Get required URL
        url = config[section]['url']

        # Initialize feed config dictionary
        feed_config = {'url': url}

        # Get optional regex filter
        if 'regex' in config[section]:
            feed_config['regex'] = config[section]['regex']

        # Get optional download path
        if 'outdir' in config[section]:
            feed_config['download_path'] = config[section]['outdir']

        feeds[short_name] = feed_config

    return feeds


def import_feeds(feeds: dict[str, dict[str, str]], force: bool = False) -> None:
    """Import feeds into the database.

    Args:
        feeds: Dictionary mapping short names to feed configs
        force: Force update even if feed exists
    """
    with db.session() as session:
        parser = RSSParser(session)

        for short_name, feed_config in feeds.items():
            try:
                url = feed_config['url']
                episode_regex = feed_config.get('regex')
                download_path = feed_config.get('download_path')

                print(f"Processing feed: {short_name} -> {url}")

                feed = session.query(Feed).filter((Feed.url == url) | (Feed.short_name == short_name)).first()

                if feed and not force:
                    print(f"✓ Feed exists: {feed.title}")

                    # Update the regex if it's provided and changed
                    if episode_regex is not None and feed.episode_regex != episode_regex:
                        old_regex = feed.episode_regex or "None"
                        feed.episode_regex = episode_regex
                        print(f"  Updated episode filter from '{old_regex}' to '{episode_regex}'")

                    if download_path is not None and feed.download_path != download_path:
                        old_download_path = feed.download_path or "None"
                        feed.download_path = download_path
                        print(f"  Updated download path from '{old_download_path}' to '{download_path}'")

                    session.commit()
                    continue

                # Parse feed with the regex filter
                feed = parser.parse_feed(
                    url,
                    short_name=short_name,
                    episode_regex=episode_regex,
                    download_path=download_path,
                    # skip_episode_parsing=True,
                )

                if feed:
                    print(f"✓ Added/updated feed: {feed.title}")
                    print(f"  Short name: {feed.short_name}")
                    if feed.episode_regex:
                        print(f"  Episode filter: {feed.episode_regex}")
                    if feed.download_path != feed.short_name:
                        print(f"  Download path: {feed.download_path}")
                else:
                    print(f"✗ Failed to parse feed: {url}")
            except IntegrityError:
                log.exception("✗ Error: Short name '%s' is already used by another feed", short_name)
                session.rollback()
                break
            except Exception:
                log.exception("✗ Error processing feed %s", short_name)
                session.rollback()


def main() -> int | None:
    parser = argparse.ArgumentParser(description="Import podcast feeds from an INI file")
    parser.add_argument("config_file", help="Path to the INI configuration file")
    parser.add_argument("--force", action="store_true", help="Force update even if feed exists")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")

    args = parser.parse_args()

    # Set up logging
    log_level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    try:
        # Parse the INI file
        feeds = parse_ini_file(args.config_file)

        if not feeds:
            print(f"No valid feeds found in {args.config_file}")
            return 1

        print(f"Found {len(feeds)} feeds in configuration file")

        # Import the feeds
        import_feeds(feeds, force=args.force)

        return 0
    except Exception as e:
        print(f"Error: {e!s}", file=sys.stderr)
        if args.debug:
            import traceback
            traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
