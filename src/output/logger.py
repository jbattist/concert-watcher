"""
CLI logger using Rich for color-coded terminal output.
"""
from __future__ import annotations

import logging
from typing import List

from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table

from src.storage.database import Concert

console = Console()


def setup_logging(level: str = "INFO") -> None:
    """Configure root logger to use Rich handler."""
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(console=console, rich_tracebacks=True, markup=True)],
    )


def log_startup(username: str, address: str, lat: float, lng: float) -> None:
    log = logging.getLogger(__name__)
    log.info(
        f"[bold green]concert-watcher started[/bold green] "
        f"| user: [cyan]{username}[/cyan] "
        f"| location: [yellow]{address}[/yellow] "
        f"({lat:.4f}, {lng:.4f})"
    )


def log_sync_summary(
    source: str,
    artist_count: int,
    new_artist_count: int,
    new_concert_count: int,
) -> None:
    log = logging.getLogger(__name__)
    log.info(
        f"[bold]{source}[/bold] sync — "
        f"artists: {artist_count} "
        f"(+{new_artist_count} new) | "
        f"new concerts: [{'bold green' if new_concert_count else 'dim'}]"
        f"{new_concert_count}[/{'bold green' if new_concert_count else 'dim'}]"
    )


def log_new_concerts(concerts: List[Concert]) -> None:
    if not concerts:
        return

    log = logging.getLogger(__name__)
    log.info(f"[bold green]{len(concerts)} new concert(s) found![/bold green]")

    table = Table(
        "Artist", "Event", "Venue", "City", "Date", "Distance",
        title="New Concerts",
        highlight=True,
    )
    for c in concerts:
        date_display = c.event_date[:10] if c.event_date else "TBD"
        dist_display = f"{c.distance_miles:.0f} mi" if c.distance_miles else "?"
        table.add_row(
            c.artist_name,
            c.event_name,
            c.venue_name,
            c.venue_city,
            date_display,
            dist_display,
        )
    console.print(table)


def log_error(message: str, exc: Exception | None = None) -> None:
    log = logging.getLogger(__name__)
    if exc:
        log.error(f"[bold red]{message}[/bold red]: {exc}", exc_info=exc)
    else:
        log.error(f"[bold red]{message}[/bold red]")
