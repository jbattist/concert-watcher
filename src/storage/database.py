"""
SQLite database — schema creation and CRUD helpers.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator, List, Optional


@dataclass
class Artist:
    id: str               # Spotify artist ID
    name: str
    source: str           # "recently_played" | "playlist" | "both"
    first_seen_at: str
    last_seen_at: str
    active: bool = True
    mb_checked: bool = False  # True once a MusicBrainz lookup has been performed
    mb_active: bool = True    # False if MusicBrainz reports the artist/band as ended
    skip_tm_search: bool = False  # True to permanently exclude from Ticketmaster searches


@dataclass
class Playlist:
    id: str               # Spotify playlist URI
    name: str
    content_hash: str
    last_checked_at: str


@dataclass
class Concert:
    id: str               # Ticketmaster event ID
    artist_id: str
    artist_name: str
    event_name: str
    venue_name: str
    venue_city: str
    event_date: str
    distance_miles: float
    ticket_url: str
    price_min: Optional[float]
    price_max: Optional[float]
    currency: Optional[str]
    first_discovered_at: str
    notified: bool = False
    filtered: bool = False  # True if attraction validation flagged this as tribute/wrong artist


class Database:
    def __init__(self, db_path: str | Path = "data/tracker.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def _conn(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(self.db_path, detect_types=sqlite3.PARSE_DECLTYPES)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS artists (
                    id              TEXT PRIMARY KEY,
                    name            TEXT NOT NULL,
                    source          TEXT NOT NULL DEFAULT 'recently_played',
                    first_seen_at   TEXT NOT NULL,
                    last_seen_at    TEXT NOT NULL,
                    active          INTEGER NOT NULL DEFAULT 1,
                    mb_checked      INTEGER NOT NULL DEFAULT 0,
                    mb_active       INTEGER NOT NULL DEFAULT 1,
                    skip_tm_search  INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS playlists (
                    id              TEXT PRIMARY KEY,
                    name            TEXT NOT NULL,
                    content_hash    TEXT NOT NULL DEFAULT '',
                    last_checked_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS concerts (
                    id                  TEXT PRIMARY KEY,
                    artist_id           TEXT NOT NULL,
                    artist_name         TEXT NOT NULL,
                    event_name          TEXT NOT NULL,
                    venue_name          TEXT NOT NULL,
                    venue_city          TEXT NOT NULL,
                    event_date          TEXT NOT NULL,
                    distance_miles      REAL NOT NULL,
                    ticket_url          TEXT NOT NULL DEFAULT '',
                    price_min           REAL,
                    price_max           REAL,
                    currency            TEXT,
                    first_discovered_at TEXT NOT NULL,
                    notified            INTEGER NOT NULL DEFAULT 0,
                    filtered            INTEGER NOT NULL DEFAULT 0,
                    FOREIGN KEY (artist_id) REFERENCES artists(id)
                );

                CREATE TABLE IF NOT EXISTS monitoring_state (
                    key     TEXT PRIMARY KEY,
                    value   TEXT NOT NULL
                );
            """)
            # Migrate existing DBs that pre-date the mb_checked / mb_active columns
            existing_cols = {
                row[1]
                for row in conn.execute("PRAGMA table_info(artists)").fetchall()
            }
            if "mb_checked" not in existing_cols:
                conn.execute(
                    "ALTER TABLE artists ADD COLUMN mb_checked INTEGER NOT NULL DEFAULT 0"
                )
            if "mb_active" not in existing_cols:
                conn.execute(
                    "ALTER TABLE artists ADD COLUMN mb_active INTEGER NOT NULL DEFAULT 1"
                )
            if "skip_tm_search" not in existing_cols:
                conn.execute(
                    "ALTER TABLE artists ADD COLUMN skip_tm_search INTEGER NOT NULL DEFAULT 0"
                )
            # Migrate concerts table
            existing_concert_cols = {
                row[1]
                for row in conn.execute("PRAGMA table_info(concerts)").fetchall()
            }
            if "filtered" not in existing_concert_cols:
                conn.execute(
                    "ALTER TABLE concerts ADD COLUMN filtered INTEGER NOT NULL DEFAULT 0"
                )

    # ------------------------------------------------------------------ #
    # Artists
    # ------------------------------------------------------------------ #

    def upsert_artist(self, artist_id: str, name: str, source: str) -> bool:
        """Insert or update an artist. Returns True if it was a new insertion."""
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            existing = conn.execute(
                "SELECT id, source FROM artists WHERE id = ?", (artist_id,)
            ).fetchone()

            if existing is None:
                conn.execute(
                    """INSERT INTO artists
                       (id, name, source, first_seen_at, last_seen_at, active,
                        mb_checked, mb_active, skip_tm_search)
                       VALUES (?, ?, ?, ?, ?, 1, 0, 1, 0)""",
                    (artist_id, name, source, now, now),
                )
                return True

            # Merge source labels if needed
            current_source = existing["source"]
            if current_source != source and current_source != "both":
                merged = "both" if {current_source, source} == {"recently_played", "playlist"} else source
            else:
                merged = current_source

            conn.execute(
                """UPDATE artists SET name=?, source=?, last_seen_at=?, active=1
                   WHERE id=?""",
                (name, merged, now, artist_id),
            )
            return False

    def get_active_artists(self) -> List[Artist]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM artists WHERE active=1 ORDER BY name"
            ).fetchall()
        return [_row_to_artist(r) for r in rows]

    def deactivate_artists_not_in(self, artist_ids: List[str]) -> None:
        """Mark artists inactive if they are no longer seen in any source."""
        if not artist_ids:
            return
        placeholders = ",".join("?" * len(artist_ids))
        with self._conn() as conn:
            conn.execute(
                f"UPDATE artists SET active=0 WHERE id NOT IN ({placeholders})",
                artist_ids,
            )

    def get_artists_needing_mb_check(self) -> List[Artist]:
        """Return active artists that have not yet had a MusicBrainz lookup."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM artists WHERE active=1 AND mb_checked=0 ORDER BY name"
            ).fetchall()
        return [_row_to_artist(r) for r in rows]

    def set_mb_result(self, artist_id: str, mb_active: bool) -> None:
        """Record the MusicBrainz lookup result for an artist."""
        with self._conn() as conn:
            conn.execute(
                "UPDATE artists SET mb_checked=1, mb_active=? WHERE id=?",
                (int(mb_active), artist_id),
            )

    def get_concert_searchable_artists(self) -> List[Artist]:
        """Active artists that MusicBrainz has not flagged as disbanded/ended,
        and that have not been manually excluded from Ticketmaster searches."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM artists WHERE active=1 AND mb_active=1 AND skip_tm_search=0 ORDER BY name"
            ).fetchall()
        return [_row_to_artist(r) for r in rows]

    def set_skip_tm_search(self, artist_id: str, skip: bool) -> None:
        """Permanently exclude (or re-include) an artist from Ticketmaster searches."""
        with self._conn() as conn:
            conn.execute(
                "UPDATE artists SET skip_tm_search=? WHERE id=?",
                (int(skip), artist_id),
            )

    # ------------------------------------------------------------------ #
    # Playlists
    # ------------------------------------------------------------------ #

    def upsert_playlist(self, playlist_id: str, name: str, content_hash: str) -> bool:
        """Returns True if hash changed (playlist needs re-processing)."""
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            existing = conn.execute(
                "SELECT content_hash FROM playlists WHERE id=?", (playlist_id,)
            ).fetchone()

            if existing is None:
                conn.execute(
                    """INSERT INTO playlists (id, name, content_hash, last_checked_at)
                       VALUES (?, ?, ?, ?)""",
                    (playlist_id, name, content_hash, now),
                )
                return True

            changed = existing["content_hash"] != content_hash
            conn.execute(
                "UPDATE playlists SET name=?, content_hash=?, last_checked_at=? WHERE id=?",
                (name, content_hash, now, playlist_id),
            )
            return changed

    # ------------------------------------------------------------------ #
    # Concerts
    # ------------------------------------------------------------------ #

    def insert_concert(self, concert: Concert) -> bool:
        """Insert a concert if not already present. Returns True if new."""
        with self._conn() as conn:
            existing = conn.execute(
                "SELECT id FROM concerts WHERE id=?", (concert.id,)
            ).fetchone()
            if existing:
                return False

            conn.execute(
                """INSERT INTO concerts
                   (id, artist_id, artist_name, event_name, venue_name, venue_city,
                    event_date, distance_miles, ticket_url, price_min, price_max,
                    currency, first_discovered_at, notified, filtered)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    concert.id, concert.artist_id, concert.artist_name,
                    concert.event_name, concert.venue_name, concert.venue_city,
                    concert.event_date, concert.distance_miles, concert.ticket_url,
                    concert.price_min, concert.price_max, concert.currency,
                    concert.first_discovered_at, int(concert.notified),
                    int(concert.filtered),
                ),
            )
            return True

    def get_upcoming_concerts(self) -> List[Concert]:
        now = datetime.now(timezone.utc).date().isoformat()
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM concerts WHERE event_date >= ? AND filtered=0 ORDER BY event_date",
                (now,),
            ).fetchall()
        return [_row_to_concert(r) for r in rows]

    def get_new_concerts(self) -> List[Concert]:
        """Concerts that have not yet been marked as notified."""
        now = datetime.now(timezone.utc).date().isoformat()
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM concerts WHERE notified=0 AND event_date >= ? ORDER BY event_date",
                (now,),
            ).fetchall()
        return [_row_to_concert(r) for r in rows]

    def mark_all_notified(self) -> None:
        with self._conn() as conn:
            conn.execute("UPDATE concerts SET notified=1")

    # ------------------------------------------------------------------ #
    # Monitoring state (key/value store for cursors etc.)
    # ------------------------------------------------------------------ #

    def get_state(self, key: str, default: Optional[str] = None) -> Optional[str]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT value FROM monitoring_state WHERE key=?", (key,)
            ).fetchone()
        return row["value"] if row else default

    def set_state(self, key: str, value: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO monitoring_state (key, value) VALUES (?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )


def _row_to_concert(row: sqlite3.Row) -> Concert:
    d = dict(row)
    d["notified"] = bool(d["notified"])
    d["filtered"] = bool(d["filtered"])
    return Concert(**d)


def _row_to_artist(row: sqlite3.Row) -> Artist:
    d = dict(row)
    d["active"] = bool(d["active"])
    d["mb_checked"] = bool(d["mb_checked"])
    d["mb_active"] = bool(d["mb_active"])
    d["skip_tm_search"] = bool(d["skip_tm_search"])
    return Artist(**d)
