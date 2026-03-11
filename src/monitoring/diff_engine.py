"""
Diff engine — compares freshly fetched data against the database to detect
new artists and new concerts, then persists changes.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Tuple

from src.concerts.musicbrainz import MusicBrainzClient
from src.concerts.ticketmaster import TicketmasterClient, TicketmasterEvent
from src.storage.database import Concert, Database


@dataclass
class DiffResult:
    new_artist_ids: List[str]       # Spotify artist IDs that were just added
    new_concert_ids: List[str]      # Ticketmaster event IDs that are newly discovered
    total_artists: int
    total_concerts: int


def process_artist_batch(
    db: Database,
    artists: List[Tuple[str, str]],  # (artist_id, artist_name)
    source: str,                      # "recently_played" | "playlist"
) -> List[Tuple[str, str]]:
    """
    Upsert a batch of artists into the database.

    Returns the subset that are brand new (never seen before).
    """
    new_artists: List[Tuple[str, str]] = []
    for artist_id, artist_name in artists:
        is_new = db.upsert_artist(artist_id, artist_name, source)
        if is_new:
            new_artists.append((artist_id, artist_name))
    return new_artists


def run_mb_checks(db: Database, mb: MusicBrainzClient) -> Tuple[int, int]:
    """
    Run MusicBrainz "still active" checks for all artists that have not yet
    been checked.  Respects the 1 req/sec rate limit inside MusicBrainzClient.

    Returns (checked_count, skipped_count) where skipped_count is the number
    of artists marked as no longer active.
    """
    pending = db.get_artists_needing_mb_check()
    checked = 0
    skipped = 0
    for artist in pending:
        try:
            is_active = mb.is_artist_active(artist.name)
        except Exception:
            # Network error, etc. — leave mb_checked=0 so we retry next run
            continue
        db.set_mb_result(artist.id, is_active)
        checked += 1
        if not is_active:
            skipped += 1
    return checked, skipped


def search_and_store_concerts(
    db: Database,
    tm: TicketmasterClient,
    artists: List[Tuple[str, str]],  # (artist_id, artist_name)
    lat: float,
    lng: float,
    radius_miles: int,
) -> List[str]:
    """
    Search Ticketmaster for concerts for each artist and store any new ones.

    Returns a list of newly discovered event IDs.
    """
    new_event_ids: List[str] = []

    for artist_id, artist_name in artists:
        try:
            events = tm.search_events(
                artist_name=artist_name,
                lat=lat,
                lng=lng,
                radius_miles=radius_miles,
            )
        except Exception:
            # Don't let a single artist failure abort the whole batch
            continue

        for evt in events:
            concert = _event_to_concert(evt, artist_id, artist_name)
            is_new = db.insert_concert(concert)
            if is_new:
                new_event_ids.append(evt.event_id)

    return new_event_ids


def _event_to_concert(
    evt: TicketmasterEvent,
    artist_id: str,
    artist_name: str,
) -> Concert:
    return Concert(
        id=evt.event_id,
        artist_id=artist_id,
        artist_name=artist_name,
        event_name=evt.event_name,
        venue_name=evt.venue_name,
        venue_city=evt.venue_city,
        event_date=evt.event_date,
        distance_miles=evt.distance_miles,
        ticket_url=evt.ticket_url,
        price_min=evt.price_min,
        price_max=evt.price_max,
        currency=evt.currency,
        first_discovered_at=datetime.now(timezone.utc).isoformat(),
        notified=False,
        filtered=evt.filtered,
    )
