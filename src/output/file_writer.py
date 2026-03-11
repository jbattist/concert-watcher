"""
Writes the structured events.json output file consumed by spacebot.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import List

from src.storage.database import Artist, Concert, Database


def write_events_file(db: Database, output_path: str) -> None:
    """
    Generate and write events.json with full state:
      - summary counts
      - new (un-notified) concerts
      - all upcoming concerts
      - tracked artists

    After writing, marks all concerts as notified so the next write
    only surfaces genuinely new finds.
    """
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    artists = db.get_active_artists()
    upcoming = _deduplicate(db.get_upcoming_concerts())
    new_concerts = _deduplicate(db.get_new_concerts())
    new_ids = {c.id for c in new_concerts}

    # Build artist → upcoming concert count index
    artist_concert_count: dict[str, int] = {}
    for c in upcoming:
        artist_concert_count[c.artist_id] = artist_concert_count.get(c.artist_id, 0) + 1

    payload = {
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total_tracked_artists": len(artists),
            "total_upcoming_concerts": len(upcoming),
            "new_since_last_check": len(new_concerts),
        },
        "new_events": [_concert_to_dict(c, is_new=True) for c in new_concerts],
        "all_upcoming_concerts": [_concert_to_dict(c, is_new=c.id in new_ids) for c in upcoming],
        "tracked_artists": [
            {
                "id": a.id,
                "name": a.name,
                "source": a.source,
                "upcoming_concert_count": artist_concert_count.get(a.id, 0),
            }
            for a in artists
        ],
    }

    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    tmp_path.replace(path)  # atomic replace

    # Mark all current concerts as notified
    db.mark_all_notified()


def _deduplicate(concerts: List[Concert]) -> List[Concert]:
    """
    Remove duplicate Ticketmaster listings for the same show.
    Ticketmaster often returns multiple event IDs for different ticket
    packages (e.g. GA, reserved, 2-day passes) at the same venue on the
    same date.  We keep the first occurrence per
    (artist_id, venue_name, date[:10]) and discard the rest.
    """
    seen: set[tuple[str, str, str]] = set()
    result: List[Concert] = []
    for c in concerts:
        key = (c.artist_id, c.venue_name, c.event_date[:10])
        if key not in seen:
            seen.add(key)
            result.append(c)
    return result


def _concert_to_dict(c: Concert, is_new: bool = False) -> dict:
    price_range = None
    if c.price_min is not None or c.price_max is not None:
        price_range = {
            "min": c.price_min,
            "max": c.price_max,
            "currency": c.currency or "USD",
        }
    return {
        "event_id": c.id,
        "artist": c.artist_name,
        "event_name": c.event_name,
        "venue": c.venue_name,
        "city": c.venue_city,
        "date": c.event_date,
        "distance_miles": c.distance_miles,
        "ticket_url": c.ticket_url,
        "price_range": price_range,
        "is_new": is_new,
        "discovered_at": c.first_discovered_at,
    }
