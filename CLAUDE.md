# CLAUDE.md - Instructions for development

This file contains notes and commands for the podcast_manager project.

## Code Style Guidelines

1. **Type Annotations**
   - Use modern Python type annotations:
     - `list[Type]` instead of `List[Type]`
     - `dict[KeyType, ValueType]` instead of `Dict[KeyType, ValueType]`
     - `X | None` instead of `Optional[X]`
     - `tuple[X, Y]` instead of `Tuple[X, Y]`

2. **Modern Python Features**
   - Utilize the walrus operator (`:=`) for assignment expressions
   - Use f-strings for string formatting (except in logging statements)
   - Leverage structural pattern matching where appropriate (match/case)
   - Use dataclasses for data containers

3. **SQLAlchemy Patterns**
   - Use modern SQLAlchemy 2.0 patterns:
     - `select()` and `session.execute()` instead of `session.query()`
     - Use `with` statements for session context management
   - SQL Safety:
     - Always wrap raw SQL strings in `sa.text()` for proper type hints and security
     - Never use f-strings or string concatenation with raw SQL
     - Always use parameterized queries with named parameters:
       ```python
       # CORRECT
       session.execute(
           sa.text("SELECT * FROM users WHERE name = :name"),
           {"name": user_name}
       )
       
       # INCORRECT
       session.execute(f"SELECT * FROM users WHERE name = '{user_name}'")
       ```
     - Add type annotations for SQL result objects when possible

4. **Code Formatting**
   - Keep line length under 120 characters
   - Use consistent 4-space indentation

5. **Logging**
   - Never use f-strings in logging calls
   - Use `logger.debug("Message: %s", var)` pattern

6. **Imports**
   - Group imports: standard library, third-party, local
   - Use absolute imports for project modules
   - Import only what is needed

7. **Error Handling**
   - Use specific exception types when catching
   - Include informative error messages

8. **Path Handling**
   - Always use pathlib (Path objects) instead of string paths
   - Avoid os.path functions in favor of pathlib equivalents
   - Use relative paths for storage within the app
   - Convert to absolute paths only when needed for file operations

9. **DateTime Handling**
   - Always use timezone-aware datetime objects
   - Import both datetime and timezone: `from datetime import datetime, timezone`
   - Store UTC times in the database
   - Convert to local time only for display purposes
   - Use `datetime.now(timezone.utc)` instead of `datetime.now()` or `datetime.utcnow()`
   - When parsing dates with `strptime()`:
     - Prefer formats with explicit timezone offset (%z): `datetime.strptime(str, "%Y-%m-%d %H:%M:%S %z")`
     - For formats with timezone name (%Z), add tzinfo manually: 
       ```python
       parsed_date = datetime.strptime(str, "%a, %d %b %Y %H:%M:%S %Z")  # noqa: DTZ007
       aware_date = parsed_date.replace(tzinfo=timezone.utc)
       ```
   - For ISO format strings, use: `datetime.fromisoformat(str.replace("Z", "+00:00"))`
   - Explicitly mark any naive datetime objects with timezone information: `dt.replace(tzinfo=timezone.utc)`

10. **Documentation**
   - Use docstrings for all public functions, classes, and methods
   - Include type hints in addition to docstrings

## Setup Instructions

```bash
# Create a virtual environment and install dev dependencies
uv venv
uv sync

# Initialize alembic for migrations
alembic init migrations

# Update the alembic.ini file
# - Set sqlalchemy.url = sqlite:///podcast_manager.db
# - Update script_location = migrations

# Update env.py to import our models
# Add to migrations/env.py:
# from podcast_manager.models import Base
# target_metadata = Base.metadata

# Create initial migration
alembic revision --autogenerate -m "Initial migration"

# Apply migration
alembic upgrade head
```

## Common Commands

```bash
# Type checking
mypy .

# Linting/formatting
ruff check .
ruff format .  # Format code with ruff instead of black/isort

# Running the CLI
# After installation, use the 'pas' command:
pas --help

# Global Options
pas --downloads-dir "/path/to/downloads" --help  # Set custom base downloads directory

# Feed Commands
pas feed add "https://example.com/feed.xml" --short-name "example_pod" --download-path "custom/path"
pas feed add "https://example.com/feed2.xml" --episode-regex "^Episode \d+:" --no-auto-refresh
pas feed list
pas feed list --verbose
pas feed refresh  # Only refreshes feeds with auto_refresh=True
pas feed refresh --feed 1 --feed my_other_podcast  # Can refresh specific feeds regardless of auto_refresh setting

# Episode Commands
pas episode list --feed 1  # Using feed ID
pas episode list --feed my_podcast  # Using short name
pas episode download --feed my_podcast --limit 5
pas episode download --feed my_podcast --download-ignored  # Download all episodes regardless of regex filter
pas episode download --feed my_podcast --threads 10  # Use 10 concurrent downloads (default is 3)

# Database Commands
pas db clean-urls  # Clean all URLs that haven't been processed yet
pas db clean-urls --feed my_podcast  # Clean URLs for a specific feed
pas db clean-urls --force  # Re-clean all URLs, even if already processed

# Server Commands
pas server start  # Start RSS feed server on port 8080
pas server start --port 9000  # Use a different port
pas server start --debug  # Enable debug mode for access logs

# Import Commands
pas import podcast-dl import "downloads/Feed Name"  # Import a podcast-dl folder
pas import podcast-dl import "downloads/Feed Name" --short-name "custom_name"  # Override short name
pas import podcast-dl import "downloads/Feed Name" --download-path "custom/path"  # Override download path
pas import podcast-dl refresh --feed my_podcast  # Refresh existing feed from its download folder
pas import podcast-dl refresh --feed my_podcast --folder "downloads/Other Folder"  # Use custom folder

# IMPORTANT: When importing from podcast-dl, the folder MUST be within the downloads directory
# specified by the global --downloads-dir option. This ensures all media paths are stored
# as relative paths for consistent handling across the application.

# Using the INI config importer
cat << EOF > feeds.ini
[my_podcast]
url = https://example.com/feed.xml
regex = ^Episode \d+:
outdir = custom/path/for/downloads

[another_podcast]
url = https://another-example.com/rss
EOF

python parse_ini_config.py feeds.ini

# Or use the Python module directly:
python main.py --help
python -m podcast_manager.cli --help
```

## Database Notes

The application uses SQLAlchemy 2.0 ORM with SQLite by default. The models are:

- Feed: Represents a podcast RSS feed
- Episode: Represents a podcast episode
- AdSegment: Represents an ad segment in an episode

## Project Structure

```
podcast_manager/
├── src/                       # Source directory
│   └── podcast_manager/       # Main package
│       ├── models/            # SQLAlchemy models
│       │   ├── base.py        # Base model class
│       │   ├── feed.py        # Feed model
│       │   ├── episode.py     # Episode model
│       │   └── segment.py     # AdSegment model
│       ├── parsers/           # RSS feed parsers
│       │   └── rss.py         # RSS parser
│       ├── downloaders/       # Podcast downloaders
│       │   └── episode.py     # Episode downloader
│       ├── processors/        # Audio processors (to be implemented)
│       │   └── detector.py    # Ad segment detector
│       ├── db.py              # Database connection
│       └── cli.py             # Command-line interface
├── migrations/                # Alembic migrations
├── pyproject.toml             # Project metadata
└── CLAUDE.md                  # Development instructions
```
