"""
concert-watcher — entry point.

Usage:
    python -m src.main [--config path/to/config.yaml]

The daemon performs an initial full sync on startup, then runs scheduled
background jobs indefinitely until interrupted (Ctrl-C or SIGTERM).
"""
from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
from pathlib import Path

from src.auth.spotify_oauth import create_spotify_client, validate_auth
from src.concerts.geocoding import get_or_cache_coordinates
from src.concerts.musicbrainz import MusicBrainzClient
from src.concerts.ticketmaster import TicketmasterClient
from src.config import load_config
from src.monitoring.diff_engine import process_artist_batch, run_mb_checks, search_and_store_concerts
from src.monitoring.scheduler import Scheduler
from src.output.file_writer import write_events_file
from src.output.logger import console, log_error, log_new_concerts, log_startup, log_sync_summary, setup_logging
from src.sources.playlists import fetch_playlist_artists
from src.sources.recently_played import fetch_recently_played_artists
from src.storage.database import Database

log = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="concert-watcher",
        description="Monitor Spotify listening history for upcoming concerts nearby.",
    )
    parser.add_argument(
        "--config",
        default="config.yaml",
        help="Path to config.yaml (default: config.yaml)",
    )
    return parser.parse_args()


def apply_skip_list(config, db: Database) -> None:
    """
    Sync config.skip_artists → skip_tm_search flag in the DB.

    Any active artist whose name matches a name in the skip list (case-insensitive)
    is flagged skip_tm_search=1.  Previously-flagged artists whose names are no longer
    in the skip list are unflagged (skip_tm_search=0).
    """
    skip_names_lower = {n.lower() for n in config.skip_artists}
    for artist in db.get_active_artists():
        should_skip = artist.name.lower() in skip_names_lower
        if should_skip != artist.skip_tm_search:
            db.set_skip_tm_search(artist.id, should_skip)
            action = "skipping" if should_skip else "re-enabling"
            log.info(f"TM search {action}: [yellow]{artist.name}[/yellow]")


def initial_sync(config, db: Database, sp, tm: TicketmasterClient, mb: MusicBrainzClient, lat: float, lng: float) -> None:
    """
    Full sync run on startup:
      1. Recently played → artists
      2. Configured playlists → artists
      3. MusicBrainz "still active" checks for any unchecked artists
      4. Ticketmaster search for all active, MB-confirmed artists
      5. Write events.json
    """
    log.info("Running initial full sync...")

    # --- Recently played ---
    with console.status("[bold]Fetching recently played tracks...[/bold]"):
        try:
            artists, newest_ms = fetch_recently_played_artists(sp)
            if newest_ms:
                db.set_state("recently_played_cursor", str(newest_ms))
            new_rp = process_artist_batch(db, artists, source="recently_played")
            log_sync_summary("recently_played", len(artists), len(new_rp), 0)
        except Exception as exc:
            log_error("Failed to sync recently played", exc)

    # --- Playlists ---
    for playlist_uri in config.playlists:
        with console.status(f"[bold]Syncing playlist [cyan]{playlist_uri}[/cyan]...[/bold]"):
            try:
                playlist_id, name, artists, content_hash = fetch_playlist_artists(sp, playlist_uri)
                db.upsert_playlist(playlist_id, name, content_hash)
                new_pl = process_artist_batch(db, artists, source="playlist")
                log_sync_summary(f"playlist:{name}", len(artists), len(new_pl), 0)
            except Exception as exc:
                log_error(f"Failed to sync playlist {playlist_uri}", exc)

    # --- MusicBrainz activity checks ---
    with console.status("[bold]Running MusicBrainz activity checks...[/bold]"):
        try:
            checked, skipped = run_mb_checks(db, mb)
            if checked:
                log.info(
                    f"MusicBrainz: checked {checked} artist(s), "
                    f"skipped {skipped} as no longer active."
                )
        except Exception as exc:
            log_error("MusicBrainz checks failed", exc)

    # --- Concert search (only MB-confirmed active artists) ---
    try:
        searchable = db.get_concert_searchable_artists()
        artist_tuples = [(a.id, a.name) for a in searchable]
        log.info(f"Searching Ticketmaster for {len(artist_tuples)} artist(s)...")

        new_ids = search_and_store_concerts(
            db, tm, artist_tuples, lat=lat, lng=lng,
            radius_miles=config.location.radius_miles,
        )
        new_concerts = db.get_new_concerts()
        if new_concerts:
            log_new_concerts(new_concerts)
        log_sync_summary("concert_search", len(artist_tuples), 0, len(new_ids))
    except Exception as exc:
        log_error("Failed initial concert search", exc)

    # --- Write output ---
    with console.status("[bold]Writing events.json...[/bold]"):
        try:
            write_events_file(db, config.output.events_file)
            log.info(f"events.json written to [cyan]{config.output.events_file}[/cyan]")
        except Exception as exc:
            log_error("Failed to write events.json", exc)


def main() -> None:
    args = parse_args()

    # Load config
    try:
        config = load_config(args.config)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        sys.exit(1)

    # Setup logging
    setup_logging(config.output.log_level)

    # Initialize database
    db = Database(config.output.events_file.replace("events.json", "tracker.db"))

    # Spotify auth
    log.info("Authenticating with Spotify...")
    try:
        sp = create_spotify_client(config.spotify)
        username = validate_auth(sp)
    except Exception as exc:
        log_error("Spotify authentication failed", exc)
        sys.exit(1)

    # Geocode address
    try:
        lat, lng = get_or_cache_coordinates(
            config.location.address,
            db.get_state,
            db.set_state,
        )
    except Exception as exc:
        log_error("Geocoding failed", exc)
        sys.exit(1)

    log_startup(username, config.location.address, lat, lng)

    # Ticketmaster client
    tm = TicketmasterClient(api_key=config.ticketmaster.api_key)

    # MusicBrainz client
    mb = MusicBrainzClient()

    # Apply skip list from config (sets skip_tm_search flag on matching artists)
    apply_skip_list(config, db)

    # Initial full sync
    initial_sync(config, db, sp, tm, mb, lat, lng)

    # Start background scheduler
    scheduler = Scheduler(config, db, sp, tm, mb)
    scheduler.start()

    # Graceful shutdown on SIGINT / SIGTERM
    def _shutdown(signum, frame):  # type: ignore[type-arg]
        log.info("Shutting down...")
        scheduler.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    log.info("[bold green]Daemon running.[/bold green] Press Ctrl-C to stop.")

    # Keep the main thread alive
    while True:
        time.sleep(1)


if __name__ == "__main__":
    main()
