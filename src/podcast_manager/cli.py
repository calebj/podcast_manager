"""Command-line interface for podcast ad remover."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING
from xml.etree import ElementTree as ET

import click
from aiohttp import web

from .db import db
from .downloaders import EpisodeDownloader
from .models import Episode, Feed
from .parsers import PodcastDLParser, RSSParser, clean_episode_url

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def resolve_feed(session: Session, feed_identifier: int | str) -> Feed | None:
    """Resolve a feed by ID or short name.

    Args:
        session: Database session
        feed_identifier: Feed ID (int) or short name (str)

    Returns:
        Optional[Feed]: The feed if found, None otherwise
    """
    if isinstance(feed_identifier, int) or (isinstance(feed_identifier, str) and feed_identifier.isdigit()):
        # Treat as ID
        feed_id = int(feed_identifier)
        return session.query(Feed).filter(Feed.id == feed_id).first()
    else:
        # Treat as short name
        return session.query(Feed).filter(Feed.short_name == feed_identifier).first()


@click.group()
@click.option("--debug/--no-debug", default=False, help="Enable debug logging")
@click.option("--downloads-dir", type=str, default="downloads", help="Base directory for podcast downloads")
@click.pass_context
def cli(ctx: click.Context, debug: bool, downloads_dir: str) -> None:
    """Podcast Ad Remover CLI.

    Parse RSS feeds, download episodes, and remove ad segments from podcast files.

    The --downloads-dir option sets the base directory for all downloaded podcasts.
    Each feed will have its own subdirectory within this base directory.
    """
    # Set up logging
    log_level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # Initialize database
    if not Path(db.config.database).exists():
        click.echo(f"Creating database at {db.config.database}")
        db.create_tables()

    # Store global parameters in context
    ctx.ensure_object(dict)
    ctx.obj["DEBUG"] = debug
    ctx.obj["DOWNLOADS_DIR"] = downloads_dir


# Feed command group
@click.group(name="feed")
@click.pass_context
def feed_group(ctx: click.Context) -> None:
    """Commands for managing podcast feeds."""


@feed_group.command(name="add")
@click.argument("url")
@click.option("--force/--no-force", default=False, help="Force update even if feed exists")
@click.option("--short-name", type=str, help="Short name for the feed (must be unique)")
@click.option("--download-path", type=str, help="Custom download path for episodes (defaults to short_name)")
@click.option("--episode-regex", type=str, help="Regular expression to filter episode titles for download")
@click.option("--no-auto-refresh", is_flag=True, help="Exclude from automatic refresh (unless specified with --feed)")
def feed_add(
    url: str,
    force: bool,
    short_name: str | None,
    download_path: str | None,
    episode_regex: str | None,
    no_auto_refresh: bool,
) -> None:
    """Add a podcast feed to the database."""
    with db.session() as session:
        parser = RSSParser(session)

        # Check if feed already exists
        if not force:
            existing_feed = session.query(Feed).filter(Feed.url == url).first()
            if existing_feed:
                click.echo(f"Feed already exists: {existing_feed.title}")
                return

        # Check if short name is already used
        if short_name:
            existing_feed = session.query(Feed).filter(Feed.short_name == short_name).first()
            if existing_feed:
                click.echo(f"Error: Short name '{short_name}' is already used by another feed")
                return

        # Parse feed
        kwargs = {}

        # Only set auto_refresh if the no_auto_refresh flag was provided
        if no_auto_refresh:
            kwargs['auto_refresh'] = False

        feed = parser.parse_feed(url, short_name=short_name, episode_regex=episode_regex, download_path=download_path, **kwargs)

        if feed:
            click.echo(f"Added feed: {feed.title}")
            if feed.short_name:
                click.echo(f"Short name: {feed.short_name}")
            if feed.download_path:
                click.echo(f"Download path: {feed.download_path}")
            if feed.episode_regex:
                click.echo(f"Episode filter: {feed.episode_regex}")
            if not feed.auto_refresh:
                click.echo("Auto-refresh: disabled")
            click.echo(f"Found {len(feed.episodes)} episodes")
        else:
            click.echo(f"Failed to parse feed: {url}")


@feed_group.command(name="list")
@click.option("--limit", default=None, type=int, help="Limit number of feeds to show")
@click.option("--verbose", "-v", is_flag=True, help="Show detailed feed information")
def feed_list(limit: int | None, verbose: bool) -> None:
    """List all podcast feeds in the database."""
    with db.session() as session:
        query = session.query(Feed).order_by(Feed.title)

        if limit:
            query = query.limit(limit)

        feeds = query.all()

        if not feeds:
            click.echo("No feeds found")
            return

        click.echo(f"Found {len(feeds)} feeds:")
        for feed in feeds:
            episode_count = session.query(Episode).filter(Episode.feed_id == feed.id).count()
            short_name_str = f" [{feed.short_name}]" if feed.short_name else ""
            auto_refresh_str = "" if feed.auto_refresh else " (auto-refresh: off)"

            line = f"- {feed.id}: {feed.title}{short_name_str}{auto_refresh_str} ({episode_count} episodes)"

            click.echo(line)

            if verbose:
                if feed.episode_regex:
                    click.echo(f"    Episode filter: {feed.episode_regex}")
                click.echo(f"    Download path: {feed.download_path}")
                if feed.last_fetched:
                    click.echo(f"    Last fetched: {feed.last_fetched.strftime('%Y-%m-%d %H:%M:%S')}")
                click.echo(f"    URL: {feed.url}")
                click.echo("")


@feed_group.command(name="refresh")
@click.argument("feeds", nargs=-1)
def feed_refresh(feeds: tuple[str, ...]) -> None:
    """Refresh podcast feeds to get new episodes.

    If no feeds are provided, all feeds with auto_refresh=True will be refreshed.
    To refresh feeds with auto_refresh=False, specify them with the --feed option.
    """
    with db.session() as session:
        parser = RSSParser(session)

        # Determine which feeds to refresh
        if feeds:
            feed_objs: list[Feed] = []
            not_found_feeds = []

            for feed_identifier in feeds:
                feed_obj = resolve_feed(session, feed_identifier)
                if feed_obj:
                    feed_objs.append(feed_obj)
                else:
                    not_found_feeds.append(feed_identifier)

            if not_found_feeds:
                click.echo(f"No feeds found with identifiers: {', '.join(not_found_feeds)}")

            if not feed_objs:
                return
        else:
            # Only get feeds with auto_refresh=True
            feed_objs = session.query(Feed).filter(Feed.auto_refresh).all()
            if not feed_objs:
                click.echo("No feeds found with auto_refresh enabled")
                return

        click.echo(f"Refreshing {len(feed_objs)} feeds:")
        for f in feed_objs:
            short_name_str = f" [{f.short_name}]" if f.short_name else ""
            auto_refresh_str = "" if f.auto_refresh else " (auto-refresh disabled)"
            click.echo(f"Refreshing: {f.title}{short_name_str}{auto_refresh_str}")

            # Count episodes before refresh
            episode_count_before = len(f.episodes)

            # Refresh feed, preserving its configuration
            updated_feed = parser.parse_feed(
                f.url,
                short_name=f.short_name,
                episode_regex=f.episode_regex,
                # Do not pass auto_refresh to avoid changing it
            )

            if updated_feed:
                # Count new episodes
                episode_count_after = len(updated_feed.episodes)
                new_episodes = episode_count_after - episode_count_before

                click.echo(f"  ✓ Updated: {updated_feed.title}")
                click.echo(f"    Found {new_episodes} new episodes")
            else:
                click.echo(f"  ✗ Failed to refresh feed: {f.url}")


# Episode command group
@click.group(name="episode")
def episode_group() -> None:
    """Commands for managing podcast episodes."""


@episode_group.command(name="list")
@click.option("--feed", type=str, help="Feed ID or short name to list episodes for")
@click.option("--limit", default=None, type=int, help="Limit number of episodes to show")
@click.option("--downloaded/--all", default=False, help="Show only downloaded episodes")
def episode_list(
    feed: str | None,
    limit: int | None,
    downloaded: bool,
) -> None:
    """List episodes in the database."""
    with db.session() as session:
        query = session.query(Episode)

        if feed:
            feed_obj = resolve_feed(session, feed)
            if not feed_obj:
                click.echo(f"Feed not found: {feed}")
                return
            query = query.filter(Episode.feed_id == feed_obj.id)

        if downloaded:
            query = query.filter(Episode.download_filename.isnot(None))

        query = query.order_by(Episode.published_date.desc())

        if limit:
            query = query.limit(limit)

        episodes = query.all()

        if not episodes:
            click.echo("No episodes found")
            return

        click.echo(f"Found {len(episodes)} episodes:")
        for episode in episodes:
            status = "✓" if episode.download_filename else "✗"
            published = episode.published_date.strftime("%Y-%m-%d") if episode.published_date else "Unknown"
            click.echo(f"[{status}] {published} - {episode.title}")


@episode_group.command(name="download")
@click.argument("feed")
@click.option("--limit", default=None, type=int, help="Limit number of episodes to download")
@click.option("--force/--no-force", default=False, help="Force download even if already downloaded")
@click.option("--download-ignored/--no-download-ignored", default=False,
              help="Download episodes that don't match the feed's episode regex")
@click.option("--threads", default=3, type=int, help="Number of concurrent downloads")
@click.pass_context
def episode_download(
    ctx: click.Context,
    feed: str,
    limit: int | None,
    force: bool,
    download_ignored: bool,
    threads: int,
) -> None:
    """Download podcast episodes.

    By default, only episodes matching a feed's episode_regex (if set) will be downloaded.
    Use --download-ignored to download all episodes regardless of the regex.
    """
    with db.session() as session:
        downloader = EpisodeDownloader(download_dir=ctx.obj["DOWNLOADS_DIR"])

        # Resolve the feed (by ID or short name)
        feed_obj = resolve_feed(session, feed)
        if not feed_obj:
            click.echo(f"Feed not found: {feed}")
            return

        # Download episodes for specific feed
        query = session.query(Episode).filter(Episode.feed_id == feed_obj.id)

        if not force:
            query = query.filter(
                (Episode.download_filename.is_(None)) |
                (Episode.download_status != "downloaded"),
            )

        # Apply episode regex filter if present and not downloading ignored
        if feed_obj.episode_regex and not download_ignored:
            import re
            regex = re.compile(feed_obj.episode_regex)

            # Get all episodes and filter with regex
            all_episodes = query.order_by(Episode.published_date.desc()).all()

            # Only keep episodes with titles matching the regex
            episodes = [ep for ep in all_episodes if regex.search(ep.title)]

            if limit:
                episodes = episodes[:limit]
        else:
            # No regex filtering needed
            query = query.order_by(Episode.published_date.desc())

            if limit:
                query = query.limit(limit)

            episodes = query.all()

        if not episodes:
            regex_msg = ""
            if feed and not download_ignored and hasattr(feed_obj, 'episode_regex') and feed_obj.episode_regex:
                regex_msg = f" matching regex '{feed_obj.episode_regex}'"
            click.echo(f"No episodes{regex_msg} to download")
            return

        click.echo(f"Downloading {len(episodes)} episodes with {threads} concurrent downloads:")

        # If we only have one episode or threads is set to 1, use synchronous download
        if len(episodes) == 1 or threads == 1:
            for episode in episodes:
                click.echo(f"Downloading: {episode.title}")
                success, error = downloader.download_episode(episode, session, force=force)

                if success:
                    click.echo(f"  ✓ Downloaded to: {episode.download_filename}")
                else:
                    click.echo(f"  ✗ Failed: {error}")
        else:
            # Run the async download
            try:
                results = asyncio.run(downloader.download_episodes_concurrent(
                    episodes, db, max_concurrent=threads, force=force,
                ))

                # Print results
                for episode, success, error in results:
                    if success:
                        click.echo(f"  ✓ Downloaded: {episode.title} to {episode.download_filename}")
                    else:
                        click.echo(f"  ✗ Failed: {episode.title} - {error}")
            except KeyboardInterrupt:
                click.echo("Download interrupted by user")
                return


# Database command group
@click.group(name="db")
def db_group() -> None:
    """Commands for database operations."""


@db_group.command(name="clean-urls")
@click.option("--feed", type=str, help="Feed ID or short name to clean URLs for")
@click.option("--force/--no-force", default=False, help="Force re-cleaning URLs that are already clean")
def db_clean_urls(feed: str | None, force: bool) -> None:
    """Clean media URLs for episodes by removing tracking and unwanted parameters.

    This command will identify the true media URLs by stripping tracking redirect domains
    and removing any unnecessary URL parameters. This is useful for bypassing tracking
    services and ensuring direct access to media files.
    """
    with db.session() as session:
        # Determine which episodes to process
        query = session.query(Episode)

        if feed:
            feed_obj = resolve_feed(session, feed)
            if not feed_obj:
                click.echo(f"Feed not found: {feed}")
                return

            click.echo(f"Cleaning URLs for feed: {feed_obj.title}")
            query = query.filter(Episode.feed_id == feed_obj.id)

        # Skip episodes that already have clean URLs unless force=True
        if not force:
            query = query.filter(Episode.clean_media_url.is_(None))

        episodes = query.all()

        if not episodes:
            click.echo("No episodes found that need URL cleaning")
            return

        click.echo(f"Cleaning URLs for {len(episodes)} episodes:")

        for episode in episodes:
            if not episode.media_url:
                click.echo(f"  ✗ Skipping: {episode.title} (no media URL)")
                continue

            clean_url = clean_episode_url(episode.media_url)
            was_cleaned = clean_url != episode.media_url

            # Only update if the URL was actually cleaned or we're forcing
            if was_cleaned or force:
                episode.clean_media_url = clean_url
                icon = "↺" if episode.clean_media_url and force else "✓"
                click.echo(f"  {icon} Cleaned: {episode.title}")
                if was_cleaned:
                    click.echo(f"      {episode.media_url} → {clean_url}")
            else:
                click.echo(f"  ✓ No change needed: {episode.title}")

        # Commit changes
        session.commit()
        click.echo("All URLs cleaned successfully")



# podcast-dl command group
@click.group(name="podcast-dl")
def podcast_dl_group() -> None:
    """Commands for working with podcast-dl folder structures."""


@podcast_dl_group.command(name="import")
@click.argument("folder", type=click.Path(exists=True, file_okay=False, dir_okay=True))
@click.option("--short-name", type=str, help="Override short name for the feed")
@click.option("--download-path", type=str, help="Override download path for the feed")
@click.pass_context
def podcast_dl_import(
    ctx: click.Context,
    folder: str,
    short_name: str | None,
) -> None:
    """Import a podcast-dl folder structure.

    This command imports a podcast feed and its episodes from a folder created by
    podcast-dl. It expects the folder to contain a feed metadata file (*.meta.json)
    that has a feedUrl key, and episode metadata files for each episode.

    The command will not fetch any data from the internet, it only reads local files.

    IMPORTANT: The folder must be located within the downloads base directory set
    by the global --downloads-dir option. This ensures that all media paths are
    stored as relative paths.

    If --download-path is not specified, the feed will use its short_name as the download path.
    """
    # Verify that the folder is within the downloads directory
    folder_path = Path(folder).resolve()
    downloads_dir = Path(ctx.obj["DOWNLOADS_DIR"]).resolve()
    if not folder_path.is_relative_to(downloads_dir):
        click.echo(f"Error: Folder {folder_path} must be within the downloads directory {downloads_dir}")
        click.echo("Use --downloads-dir to set the appropriate base directory")
        return

    with db.session() as session:
        parser = PodcastDLParser(session)

        click.echo(f"Importing podcast-dl folder: {folder}")

        # Import folder
        rel_path = folder_path.relative_to(downloads_dir)
        feed = parser.import_folder(folder_path, rel_path=rel_path, short_name=short_name)

        if not feed:
            click.echo("Failed to import feed from folder")
            return

        # Print summary
        episode_count = session.query(Episode).filter(Episode.feed_id == feed.id).count()
        downloaded = session.query(Episode).filter(
            (Episode.feed_id == feed.id) & (Episode.download_filename.isnot(None)),
        ).count()

        click.echo(f"Imported feed: {feed.title}")
        if feed.short_name:
            click.echo(f"  Short name: {feed.short_name}")
        if feed.download_path:
            click.echo(f"  Download path: {feed.download_path}")
        click.echo(f"  {episode_count} episodes")
        click.echo(f"  {downloaded} downloaded episodes")


@podcast_dl_group.command(name="refresh")
@click.argument("feed", type=str, required=True)
@click.option("--folder", type=click.Path(exists=True, file_okay=False, dir_okay=True),
              help="Custom folder path to scan (defaults to feed's download path)")
@click.pass_context
def podcast_dl_refresh(
    ctx: click.Context,
    feed: str,
    folder: str | None,
) -> None:
    """Refresh an existing feed from a podcast-dl folder structure.

    This command scans a podcast-dl folder for new episodes and adds them to an
    existing feed. It also updates existing episodes with download paths if they are
    found in the folder but not marked as downloaded in the database.

    By default, it uses the feed's download path, but you can specify a custom folder.

    IMPORTANT: Any custom folder must be located within the downloads base directory
    set by the global --downloads-dir option. This ensures that all media paths are
    stored as relative paths.
    """
    with db.session() as session:
        # Resolve the feed
        feed_obj = resolve_feed(session, feed)
        if not feed_obj:
            click.echo(f"Feed not found: {feed}")
            return

        parser = PodcastDLParser(session)

        # Determine folder path
        downloads_dir = Path(ctx.obj["DOWNLOADS_DIR"]).resolve()

        if folder:
            folder_path = Path(folder).resolve()
            # Check that custom folder is within downloads directory
            if not folder_path.is_relative_to(downloads_dir):
                click.echo(f"Error: Folder {folder_path} must be within the downloads directory {downloads_dir}")
                click.echo("Use --downloads-dir to set the appropriate base directory")
                return
        else:
            # Use the feed's download path
            folder_path = downloads_dir / feed_obj.download_path

        if not folder_path.exists() or not folder_path.is_dir():
            click.echo(f"Folder does not exist: {folder_path}")
            return

        click.echo(f"Refreshing feed '{feed_obj.title}' from folder: {folder_path}")

        # Refresh feed from folder
        new_count, updated_count = parser.refresh_feed(feed_obj, folder_path)

        # Print summary
        episode_count = session.query(Episode).filter(Episode.feed_id == feed_obj.id).count()
        downloaded = session.query(Episode).filter(
            (Episode.feed_id == feed_obj.id) & (Episode.download_filename.isnot(None)),
        ).count()

        click.echo(f"Refreshed feed: {feed_obj.title}")
        click.echo(f"  Found {new_count} new episodes")
        click.echo(f"  Updated {updated_count} existing episodes")
        click.echo(f"  Total: {episode_count} episodes ({downloaded} downloaded)")

@click.command(name="serve")
@click.option("--port", default=8080, type=int, help="Port to run the server on")
def server_start(port: int) -> None:
    """Start an RSS feed server to proxy feeds with clean media URLs.

    This server will make feeds available at /feed/{short_name}.xml with clean media URLs.
    The server can optionally serve downloaded episode files directly from the downloads directory.
    """
    async def get_feed_xml(feed: Feed, session: Session) -> str:
        """Generate cleaned RSS XML for the feed.

        Args:
            feed: Feed to generate XML for
            session: Database session

        Returns:
            str: XML string
        """
        # Create the root element for the RSS feed
        rss = ET.Element("rss", {
            "version": "2.0",
            "xmlns:itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd",
            "xmlns:content": "http://purl.org/rss/1.0/modules/content/",
            "xmlns:atom": "http://www.w3.org/2005/Atom",
        })

        # Create the channel element
        channel = ET.SubElement(rss, "channel")

        # Add basic feed information
        ET.SubElement(channel, "title").text = feed.title
        if feed.description:
            ET.SubElement(channel, "description").text = feed.description
        if feed.language:
            ET.SubElement(channel, "language").text = feed.language
        if feed.website_url:
            ET.SubElement(channel, "link").text = feed.website_url

        # Add iTunes specific tags
        if feed.author:
            ET.SubElement(channel, "itunes:author").text = feed.author

        # Add image if available
        if feed.image_url:
            ET.SubElement(channel, "itunes:image", {"href": feed.image_url})
            img = ET.SubElement(channel, "image")
            ET.SubElement(img, "url").text = feed.image_url
            ET.SubElement(img, "title").text = feed.title
            if feed.website_url:
                ET.SubElement(img, "link").text = feed.website_url

        # Add last build date (using UTC timezone)
        now = datetime.now(UTC).strftime("%a, %d %b %Y %H:%M:%S GMT")
        ET.SubElement(channel, "lastBuildDate").text = now

        # Get all episodes for the feed
        episodes = session.query(Episode).filter(Episode.feed_id == feed.id).order_by(Episode.published_date.desc()).all()

        # Server URL for episode media files (to be used if downloaded)
        # server_url = f"http://localhost:{port}"

        # Add each episode as an item
        for episode in episodes:
            item = ET.SubElement(channel, "item")

            # Add basic episode information
            ET.SubElement(item, "title").text = episode.title
            if episode.description:
                description = ET.SubElement(item, "description")
                description.text = episode.description

            # Add guid
            guid = ET.SubElement(item, "guid", {"isPermaLink": "false"})
            guid.text = episode.guid

            # Add publication date if available
            if episode.published_date:
                pub_date = episode.published_date.strftime("%a, %d %b %Y %H:%M:%S GMT")
                ET.SubElement(item, "pubDate").text = pub_date

            # Add enclosure with clean media URL
            media_url = episode.clean_media_url or episode.media_url
            if media_url:
                ET.SubElement(item, "enclosure", {
                    "url": media_url,
                    "type": episode.media_type or "audio/mpeg",
                    "length": str(episode.media_size or 0),
                })

            # Add duration if available
            if episode.duration:
                minutes, seconds = divmod(episode.duration, 60)
                hours, minutes = divmod(minutes, 60)
                duration_str = f"{hours}:{minutes:02d}:{seconds:02d}" if hours > 0 else f"{minutes}:{seconds:02d}"
                ET.SubElement(item, "itunes:duration").text = duration_str

        # Convert to string
        return ET.tostring(rss, encoding="unicode")

    # Set up routes
    routes = web.RouteTableDef()

    @routes.get("/")
    async def index(request: web.Request) -> web.Response:
        """Index page listing available feeds."""
        with db.session() as session:
            feeds = session.query(Feed).order_by(Feed.title).all()

            html = """
            <!DOCTYPE html>
            <html>
            <head>
                <title>Podcast Feeds</title>
                <meta name="viewport" content="width=device-width, initial-scale=1">
                <style>
                    body {
                        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
                        line-height: 1.6;
                        color: #333;
                        max-width: 800px;
                        margin: 0 auto;
                        padding: 20px;
                    }
                    h1 {
                        color: #2c3e50;
                        border-bottom: 1px solid #eee;
                        padding-bottom: 10px;
                    }
                    .feed-list {
                        list-style: none;
                        padding: 0;
                    }
                    .feed-item {
                        margin-bottom: 15px;
                        padding: 15px;
                        background-color: #f9f9f9;
                        border-radius: 5px;
                        box-shadow: 0 1px 3px rgba(0,0,0,0.1);
                    }
                    .feed-item:hover {
                        background-color: #f1f1f1;
                    }
                    .feed-title {
                        font-weight: bold;
                        margin-bottom: 5px;
                    }
                    .feed-link {
                        display: inline-block;
                        text-decoration: none;
                        color: #3498db;
                        padding: 5px 10px;
                        border-radius: 3px;
                        background-color: #e3f2fd;
                        margin-top: 5px;
                    }
                    .feed-link:hover {
                        background-color: #bbdefb;
                    }
                    .feed-meta {
                        font-size: 0.9em;
                        color: #7f8c8d;
                    }
                    .no-feeds {
                        padding: 20px;
                        background-color: #f8d7da;
                        border-radius: 5px;
                        color: #721c24;
                    }
                    footer {
                        margin-top: 30px;
                        padding-top: 10px;
                        border-top: 1px solid #eee;
                        font-size: 0.8em;
                        color: #7f8c8d;
                    }
                </style>
                <script>
                    document.addEventListener('DOMContentLoaded', function() {
                        // Add click handlers for copy buttons
                        document.querySelectorAll('.copy-btn').forEach(btn => {
                            btn.addEventListener('click', function(e) {
                                e.preventDefault();
                                const url = this.getAttribute('data-url');
                                navigator.clipboard.writeText(url).then(() => {
                                    // Change button text temporarily
                                    const originalText = this.textContent;
                                    this.textContent = 'Copied!';
                                    this.style.backgroundColor = '#c8e6c9';

                                    // Reset after 2 seconds
                                    setTimeout(() => {
                                        this.textContent = originalText;
                                        this.style.backgroundColor = '';
                                    }, 2000);
                                });
                            });
                        });
                    });
                </script>
            </head>
            <body>
                <h1>Available Podcast Feeds</h1>
            """

            if not feeds:
                html += '<div class="no-feeds">No feeds available. Add feeds using the command line tool.</div>'
            else:
                html += '<ul class="feed-list">'

                for feed in feeds:
                    if feed.short_name:
                        feed_url = f"/feed/{feed.short_name}.xml"
                        episode_count = session.query(Episode).filter(Episode.feed_id == feed.id).count()

                        html += f'''
                        <li class="feed-item">
                            <div class="feed-title">{feed.title}</div>
                            <div class="feed-meta">
                                {episode_count} episodes
                                {f" • Last updated: {feed.last_fetched.strftime('%Y-%m-%d')}" if feed.last_fetched else ""}
                            </div>
                            <a class="feed-link" href="{feed_url}">RSS Feed</a>
                            <a class="feed-link copy-btn" data-url="{request.url.scheme}://{request.url.host}:{request.url.port}{feed_url}">Copy URL</a>
                        </li>
                        '''

                html += '</ul>'

            html += """
                <footer>
                    Powered by Podcast Ad Remover
                </footer>
            </body>
            </html>
            """

            return web.Response(text=html, content_type="text/html")

    @routes.get("/feed/{short_name}.xml")
    async def serve_feed(request: web.Request) -> web.Response:
        """Serve an RSS feed with clean media URLs."""
        short_name = request.match_info["short_name"]

        with db.session() as session:
            feed = session.query(Feed).filter(Feed.short_name == short_name).first()

            if not feed:
                return web.Response(text=f"Feed not found: {short_name}", status=404)

            try:
                xml = await get_feed_xml(feed, session)
                return web.Response(text=xml, content_type="application/xml")
            except Exception as e:
                return web.Response(text=f"Error generating feed: {e!s}", status=500)

    # Set up the web app
    app = web.Application()
    app.add_routes(routes)

    click.echo(f"Starting RSS feed server on http://localhost:{port}")
    click.echo("Available feeds will be accessible at:")
    click.echo(f"  http://localhost:{port}/feed/<short_name>.xml")
    click.echo("Press CTRL+C to stop the server")

    # Run the web app
    web.run_app(app, port=port, print=None)


# Add command groups to the main CLI
cli.add_command(feed_group)
cli.add_command(episode_group)
cli.add_command(db_group)
cli.add_command(podcast_dl_group)
cli.add_command(server_start)


if __name__ == "__main__":
    cli()
