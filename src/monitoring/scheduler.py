"""
APScheduler-based polling orchestrator.
Manages three recurring jobs:
  1. recently_played  — every N minutes (default 60)
  2. playlist_sync    — every N minutes (default 360)
  3. concert_search   — every N minutes (default 720)
"""
from __future__ import annotations

import logging
from typing import List, Optional, Tuple

import spotipy
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from src.concerts.geocoding import get_or_cache_coordinates
from src.concerts.musicbrainz import MusicBrainzClient
from src.concerts.ticketmaster import TicketmasterClient
from src.config import AppConfig
from src.monitoring.diff_engine import process_artist_batch, run_mb_checks, search_and_store_concerts
from src.output.file_writer import write_events_file
from src.output.logger import log_error, log_new_concerts, log_sync_summary
from src.sources.playlists import fetch_playlist_artists
from src.sources.recently_played import fetch_recently_played_artists
from src.storage.database import Database

log = logging.getLogger(__name__)


class Scheduler:
    def __init__(
        self,
        config: AppConfig,
        db: Database,
        sp: spotipy.Spotify,
        tm: TicketmasterClient,
        mb: MusicBrainzClient,
    ) -> None:
        self.config = config
        self.db = db
        self.sp = sp
        self.tm = tm
        self.mb = mb
        self._scheduler = BackgroundScheduler(timezone="UTC")

    # ------------------------------------------------------------------ #
    # Public interface
    # ------------------------------------------------------------------ #

    def start(self) -> None:
        mon = self.config.monitoring

        self._scheduler.add_job(
            self._recently_played_job,
            trigger=IntervalTrigger(minutes=mon.recently_played_interval_minutes),
            id="recently_played",
            name="Recently Played Sync",
            max_instances=1,
            coalesce=True,
        )

        self._scheduler.add_job(
            self._playlist_sync_job,
            trigger=IntervalTrigger(minutes=mon.playlist_interval_minutes),
            id="playlist_sync",
            name="Playlist Sync",
            max_instances=1,
            coalesce=True,
        )

        self._scheduler.add_job(
            self._concert_search_job,
            trigger=IntervalTrigger(minutes=mon.concert_search_interval_minutes),
            id="concert_search",
            name="Full Concert Search",
            max_instances=1,
            coalesce=True,
        )

        self._scheduler.start()
        log.info(
            "Scheduler started — "
            f"recently_played every {mon.recently_played_interval_minutes}m, "
            f"playlists every {mon.playlist_interval_minutes}m, "
            f"concerts every {mon.concert_search_interval_minutes}m"
        )

    def shutdown(self) -> None:
        self._scheduler.shutdown(wait=False)
        log.info("Scheduler stopped.")

    # ------------------------------------------------------------------ #
    # Jobs
    # ------------------------------------------------------------------ #

    def _recently_played_job(self) -> None:
        log.debug("Running: recently_played job")
        try:
            cursor_str = self.db.get_state("recently_played_cursor")
            after_ms = int(cursor_str) if cursor_str else None

            artists, newest_ms = fetch_recently_played_artists(self.sp, after_ms=after_ms)

            if newest_ms:
                self.db.set_state("recently_played_cursor", str(newest_ms))

            new_artists = process_artist_batch(self.db, artists, source="recently_played")
            new_concert_ids = self._search_for_new_artists(new_artists)
            self._refresh_output(new_concert_ids)

            log_sync_summary(
                "recently_played",
                artist_count=len(artists),
                new_artist_count=len(new_artists),
                new_concert_count=len(new_concert_ids),
            )
        except Exception as exc:
            log_error("recently_played job failed", exc)

    def _playlist_sync_job(self) -> None:
        log.debug("Running: playlist_sync job")
        if not self.config.playlists:
            log.debug("No playlists configured, skipping.")
            return

        try:
            total_artists: List[Tuple[str, str]] = []
            total_new_artists: List[Tuple[str, str]] = []
            total_new_concerts: List[str] = []

            for playlist_uri in self.config.playlists:
                playlist_id, name, artists, content_hash = fetch_playlist_artists(
                    self.sp, playlist_uri
                )
                changed = self.db.upsert_playlist(playlist_id, name, content_hash)
                total_artists.extend(artists)

                if changed:
                    new_artists = process_artist_batch(self.db, artists, source="playlist")
                    total_new_artists.extend(new_artists)
                    new_ids = self._search_for_new_artists(new_artists)
                    total_new_concerts.extend(new_ids)
                else:
                    log.debug(f"Playlist '{name}' unchanged, skipping artist diff.")

            self._refresh_output(total_new_concerts)
            log_sync_summary(
                "playlist_sync",
                artist_count=len(set(a[0] for a in total_artists)),
                new_artist_count=len(total_new_artists),
                new_concert_count=len(total_new_concerts),
            )
        except Exception as exc:
            log_error("playlist_sync job failed", exc)

    def _concert_search_job(self) -> None:
        """Full sweep: check MB for new artists, then search Ticketmaster for all active artists."""
        log.debug("Running: full concert_search job")
        try:
            lat, lng = get_or_cache_coordinates(
                self.config.location.address,
                self.db.get_state,
                self.db.set_state,
            )

            # Run MusicBrainz activity checks for any artists not yet checked
            checked, skipped = run_mb_checks(self.db, self.mb)
            if checked:
                log.info(
                    f"MusicBrainz: checked {checked} artist(s), "
                    f"skipped {skipped} as no longer active."
                )

            # Search only artists confirmed active by MB (or not yet checked — treated as active)
            searchable = self.db.get_concert_searchable_artists()
            artist_tuples = [(a.id, a.name) for a in searchable]

            new_ids = search_and_store_concerts(
                self.db,
                self.tm,
                artist_tuples,
                lat=lat,
                lng=lng,
                radius_miles=self.config.location.radius_miles,
            )
            self._refresh_output(new_ids)
            log_sync_summary(
                "concert_search",
                artist_count=len(artist_tuples),
                new_artist_count=0,
                new_concert_count=len(new_ids),
            )
        except Exception as exc:
            log_error("concert_search job failed", exc)

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    def _search_for_new_artists(self, new_artists: List[Tuple[str, str]]) -> List[str]:
        """
        Run MB checks then immediately search Ticketmaster for brand-new artists.
        Artists that MB flags as ended are skipped.
        """
        if not new_artists:
            return []
        try:
            lat, lng = get_or_cache_coordinates(
                self.config.location.address,
                self.db.get_state,
                self.db.set_state,
            )
            # Check any that are still unchecked (should be all of new_artists)
            run_mb_checks(self.db, self.mb)

            # Only search for artists that are MB-active
            new_artist_ids = {aid for aid, _ in new_artists}
            searchable = [
                (a.id, a.name)
                for a in self.db.get_concert_searchable_artists()
                if a.id in new_artist_ids
            ]
            if not searchable:
                return []
            return search_and_store_concerts(
                self.db,
                self.tm,
                searchable,
                lat=lat,
                lng=lng,
                radius_miles=self.config.location.radius_miles,
            )
        except Exception as exc:
            log_error("Concert search for new artists failed", exc)
            return []

    def _refresh_output(self, new_concert_ids: List[str]) -> None:
        """Write events.json and log any newly found concerts."""
        try:
            # Log new concerts before marking them notified
            if new_concert_ids:
                new_concerts = db_get_concerts_by_ids(self.db, new_concert_ids)
                log_new_concerts(new_concerts)
            write_events_file(self.db, self.config.output.events_file)
        except Exception as exc:
            log_error("Failed to write events.json", exc)


def db_get_concerts_by_ids(db: Database, ids: List[str]):  # type: ignore[return]
    """Fetch Concert objects for a list of event IDs."""
    all_new = db.get_new_concerts()
    id_set = set(ids)
    return [c for c in all_new if c.id in id_set]
