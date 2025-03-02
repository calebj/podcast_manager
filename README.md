# Podcast Manager

An application to keep track of RSS feeds and episodes, with plans to build an ad-removing RSS feed proxy.

## Features

- Parse RSS feeds to get podcast metadata
- Download podcast episodes
- Store podcast and episode metadata in a database
- Strip tracking redirects from media URLs
- Identify and remove ad segments from podcast audio files (in progress)

## Installation

### Install for development

```bash
# Create .venv in the project folder
uv venv
uv sync
```

### Install as package

```bash
# Create a virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install the package
pip install .
```

## Database Setup

For now this project uses sqlite. Alembic is set to use `./podcast_manager.db`, which is created automatically with

```bash
alembic upgrade head
```

## Usage

```bash
# Global options
pas --downloads-dir /path/to/downloads  # The directory for all podcast downloads, defaults to ./downloads

# Feed management
pas feed add "https://example.com/feed.xml" --short-name "example_pod"
pas feed list
pas feed refresh --feed example_pod

# Episode management
pas episode list --feed example_pod
pas episode download --feed example_pod --limit 5  # Only download 5 files
pas episode download --feed example_pod --threads 10  # Concurrent downloads

# Database operations
pas db clean-urls --feed example_pod  # Batch clean media URLs without downloading

# Serve feeds from database
pas serve

# Importing feed and episodes from a podcast-dl archive
pas import podcast-dl import "downloads/My Podcast"

# Merge/update episodes from media+meta.json in archive folder
pas import podcast-dl refresh --feed my_podcast
```

The global `--downloads-dir` option can be used with any command and sets the base directory where podcasts will be downloaded. Each feed will have its own subdirectory within this base directory, determined by the feed's `download_path` (which defaults to the feed's `short_name`).

All media files are stored with paths relative to their feed's download folder. Episodes only store the filename part of the path, and the complete path is constructed at runtime by combining:
- The global downloads directory 
- The feed's download path
- The episode's download filename

This approach makes it easy to move or relocate the entire downloads directory while maintaining correct references.

## Development

```bash
# Check for updates
uv sync -U

# Run tests (just url cleaning for now)
pytest

# Lint
ruff check

# Type check
mypy podcast_manager
```

## Credits

Much inspiration was taken from @lightpohl's [podcast-dl](https://github.com/lightpohl/podcast-dl).

This project has been built with the assistance of Claude, Anthropic's AI assistant.
