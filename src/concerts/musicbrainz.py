"""
MusicBrainz lookup — determines whether an artist/band is still active.

Uses the MusicBrainz Search API (no auth required).
Rate limit: 1 request per second, enforced here.
A custom User-Agent is required by MusicBrainz's terms of service.

Logic:
  1. Search for the artist by name, take the top result whose score >= 85.
  2. Fetch the full artist record to get the `life-span` field.
  3. Return False (not active) only if `life-span.ended` is explicitly True.
  4. If no confident match is found, or MB is unreachable, return True (assume
     active) so we don't accidentally suppress real concerts.
"""
from __future__ import annotations

import time
from typing import Optional

import requests

_BASE_URL = "https://musicbrainz.org/ws/2"
_USER_AGENT = "concert-watcher/1.0 (https://github.com/local/concert-watcher)"

# MusicBrainz Terms of Service: max 1 req/sec for non-commercial use
_MIN_REQUEST_INTERVAL_SECONDS = 1.1  # slightly over 1 s to be safe


class MusicBrainzClient:
    def __init__(self) -> None:
        self._last_request_at: float = 0.0
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": _USER_AGENT,
            "Accept": "application/json",
        })

    def is_artist_active(self, artist_name: str) -> bool:
        """
        Returns True if the artist appears to be currently active (or if the
        status is unknown), False if MusicBrainz explicitly marks them as ended.
        """
        mbid = self._search_artist_mbid(artist_name)
        if mbid is None:
            # Could not find a confident match — assume active
            return True

        ended = self._fetch_life_span_ended(mbid)
        if ended is None:
            # Couldn't retrieve the detail page — assume active
            return True

        return not ended  # active = not ended

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _search_artist_mbid(self, artist_name: str) -> Optional[str]:
        """Search MB for the artist; return the MBID of the best match or None."""
        self._rate_limit()
        try:
            resp = self._session.get(
                f"{_BASE_URL}/artist",
                params={"query": f'artist:"{artist_name}"', "limit": 5, "fmt": "json"},
                timeout=10,
            )
        except requests.RequestException:
            return None

        if resp.status_code != 200:
            return None

        try:
            data = resp.json()
        except ValueError:
            return None

        artists = data.get("artists") or []
        for candidate in artists:
            score = int(candidate.get("score", 0))
            if score >= 85:
                return candidate.get("id")

        return None

    def _fetch_life_span_ended(self, mbid: str) -> Optional[bool]:
        """
        Fetch the full artist record and return the `life-span.ended` boolean.
        Returns None if the request fails or the field is missing.
        """
        self._rate_limit()
        try:
            resp = self._session.get(
                f"{_BASE_URL}/artist/{mbid}",
                params={"inc": "aliases", "fmt": "json"},
                timeout=10,
            )
        except requests.RequestException:
            return None

        if resp.status_code != 200:
            return None

        try:
            data = resp.json()
        except ValueError:
            return None

        life_span = data.get("life-span") or {}
        ended = life_span.get("ended")
        if isinstance(ended, bool):
            return ended
        # Some records use the string "true"/"false"
        if isinstance(ended, str):
            return ended.lower() == "true"

        return None  # field absent — assume active

    def _rate_limit(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < _MIN_REQUEST_INTERVAL_SECONDS:
            time.sleep(_MIN_REQUEST_INTERVAL_SECONDS - elapsed)
        self._last_request_at = time.monotonic()
