"""
Fetch recently played tracks from Spotify and extract unique artists.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import spotipy

# State key used to persist the cursor between runs
_CURSOR_KEY = "recently_played_cursor"


def fetch_recently_played_artists(
    sp: spotipy.Spotify,
    after_ms: Optional[int] = None,
) -> Tuple[List[Tuple[str, str]], Optional[int]]:
    """
    Fetch recently played tracks and return unique (artist_id, artist_name) pairs.

    Args:
        sp:        Authenticated Spotify client.
        after_ms:  Unix timestamp in milliseconds. Only tracks played after this
                   time are returned. Pass None to fetch the latest 50 tracks.

    Returns:
        A tuple of:
          - List of unique (artist_id, artist_name) tuples.
          - The newest `played_at` timestamp in milliseconds to use as the next cursor,
            or None if no tracks were returned.
    """
    kwargs: Dict = {"limit": 50}
    if after_ms is not None:
        kwargs["after"] = after_ms

    result = sp.current_user_recently_played(**kwargs)
    items = (result or {}).get("items", []) or []

    if not items:
        return [], None

    seen: Dict[str, str] = {}  # artist_id -> artist_name
    newest_ms: Optional[int] = None

    for item in items:
        track = item.get("track") or {}
        played_at = item.get("played_at", "")

        # Convert played_at ISO string to milliseconds for cursor storage
        if played_at:
            ts_ms = _iso_to_ms(played_at)
            if newest_ms is None or ts_ms > newest_ms:
                newest_ms = ts_ms

        for artist in track.get("artists") or []:
            artist_id = artist.get("id")
            artist_name = artist.get("name")
            if artist_id and artist_name and artist_id not in seen:
                seen[artist_id] = artist_name

    return list(seen.items()), newest_ms


def _iso_to_ms(iso: str) -> int:
    """Convert an ISO 8601 string (e.g. '2026-03-10T14:30:00.000Z') to Unix ms."""
    from datetime import datetime, timezone

    # Strip trailing Z and parse
    iso_clean = iso.rstrip("Z").split("+")[0]
    try:
        dt = datetime.fromisoformat(iso_clean).replace(tzinfo=timezone.utc)
    except ValueError:
        return 0
    return int(dt.timestamp() * 1000)
