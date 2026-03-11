"""
Ticketmaster Discovery API client.
Searches for music events near a lat/lng for a given artist.
Includes rate limiting and retry logic.

Attraction validation
---------------------
Ticketmaster's keyword search matches artist names anywhere in event titles,
which returns tribute bands, cover shows, and unrelated acts.  We guard
against this by checking the ``_embedded.attractions`` list that TM includes
on each event: if attractions are present, at least one must closely match
the artist name we searched for.  Events with *no* attractions listed are
passed through (some legitimate events omit the field).
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional

import requests

_BASE_URL = "https://app.ticketmaster.com/discovery/v2"

# Ticketmaster free tier: 5000 calls/day (~3.47/min).
# We enforce a conservative minimum gap between requests.
_MIN_REQUEST_INTERVAL_SECONDS = 0.25  # 4 req/s max; well within daily budget


@dataclass
class TicketmasterEvent:
    event_id: str
    event_name: str
    venue_name: str
    venue_city: str
    event_date: str          # ISO 8601 string
    distance_miles: float
    ticket_url: str
    price_min: Optional[float]
    price_max: Optional[float]
    currency: Optional[str]
    filtered: bool = False   # True if attraction validation failed (tribute/wrong artist)


class TicketmasterClient:
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self._last_request_at: float = 0.0

    def search_events(
        self,
        artist_name: str,
        lat: float,
        lng: float,
        radius_miles: int = 100,
        max_pages: int = 3,
    ) -> List[TicketmasterEvent]:
        """
        Search for upcoming music events for `artist_name` within `radius_miles`
        of the given lat/lng.

        Returns a list of TicketmasterEvent objects, deduplicated by event ID.
        """
        events: dict[str, TicketmasterEvent] = {}
        page = 0

        while page < max_pages:
            data = self._get_events_page(
                artist_name=artist_name,
                lat=lat,
                lng=lng,
                radius_miles=radius_miles,
                page=page,
            )
            if data is None:
                break

            embedded = data.get("_embedded") or {}
            raw_events = embedded.get("events") or []
            for raw in raw_events:
                evt = _parse_event(raw, artist_name)
                if evt and evt.event_id not in events:
                    events[evt.event_id] = evt

            # Pagination: check if there are more pages
            page_info = data.get("page") or {}
            total_pages = page_info.get("totalPages", 1)
            page += 1
            if page >= total_pages:
                break

        return list(events.values())

    def _get_events_page(
        self,
        artist_name: str,
        lat: float,
        lng: float,
        radius_miles: int,
        page: int,
        max_retries: int = 3,
    ) -> Optional[dict]:
        """Fetch a single page of events. Retries on 429 / 5xx."""
        params = {
            "apikey": self.api_key,
            "keyword": artist_name,
            "latlong": f"{lat},{lng}",
            "radius": str(radius_miles),
            "unit": "miles",
            "classificationName": "music",
            "sort": "date,asc",
            "size": 50,
            "page": page,
        }

        for attempt in range(max_retries):
            self._rate_limit()
            try:
                resp = requests.get(
                    f"{_BASE_URL}/events.json",
                    params=params,
                    timeout=15,
                )
            except requests.RequestException as exc:
                if attempt == max_retries - 1:
                    raise
                time.sleep(2 ** attempt)
                continue

            if resp.status_code == 200:
                return resp.json()

            if resp.status_code == 429:
                # Respect Retry-After header if present
                retry_after = int(resp.headers.get("Retry-After", "5"))
                time.sleep(retry_after)
                continue

            if resp.status_code in (500, 502, 503, 504):
                time.sleep(2 ** attempt)
                continue

            if resp.status_code == 401:
                raise ValueError("Ticketmaster API key is invalid or expired.")

            # 404 typically means no results — not an error
            if resp.status_code == 404:
                return None

            resp.raise_for_status()

        return None

    def _rate_limit(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < _MIN_REQUEST_INTERVAL_SECONDS:
            time.sleep(_MIN_REQUEST_INTERVAL_SECONDS - elapsed)
        self._last_request_at = time.monotonic()


def _normalize(name: str) -> str:
    """Lowercase and strip all non-alphanumeric characters for fuzzy comparison."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _attraction_matches_artist(artist_name: str, attraction_name: str) -> bool:
    """
    Return True if the TM attraction name is the same act as the searched artist.

    Rules (applied to normalized strings — lowercase, no punctuation/spaces):
    - Exact match, OR
    - Attraction starts with artist name (handles "Dave Matthews Band" when
      searching "Dave Matthews"), OR
    - Artist starts with attraction name (handles the reverse).

    This rejects tribute/cover names like "Haus Of Monsters- A Lady Gaga Tribute"
    which do not start with "ladygaga".
    """
    a = _normalize(artist_name)
    b = _normalize(attraction_name)
    if a == b:
        return True
    if b.startswith(a) or a.startswith(b):
        return True
    return False


def _parse_event(raw: dict, artist_name: str) -> Optional[TicketmasterEvent]:
    """Parse a raw Ticketmaster event dict into a TicketmasterEvent."""
    try:
        event_id = raw.get("id")
        if not event_id:
            return None

        # Validate that the actual performer matches the searched artist.
        # If TM has listed attractions, at least one must match; if the list is
        # absent we give the event the benefit of the doubt.
        attractions = ((raw.get("_embedded") or {}).get("attractions") or [])
        attraction_mismatch = bool(attractions) and not any(
            _attraction_matches_artist(artist_name, a.get("name", ""))
            for a in attractions
        )

        event_name = raw.get("name", "Unknown Event")

        # Venue info
        venues = ((raw.get("_embedded") or {}).get("venues") or [])
        venue = venues[0] if venues else {}
        venue_name = venue.get("name", "Unknown Venue")
        city = (venue.get("city") or {}).get("name", "")
        state = (venue.get("state") or {}).get("stateCode", "")
        venue_city = f"{city}, {state}".strip(", ")

        # Date/time
        dates = raw.get("dates") or {}
        start = dates.get("start") or {}
        event_date = start.get("dateTime") or start.get("localDate") or ""

        # Filter out past events
        if event_date:
            try:
                if event_date.endswith("Z") or "T" in event_date:
                    dt = datetime.fromisoformat(event_date.replace("Z", "+00:00"))
                else:
                    dt = datetime.fromisoformat(event_date).replace(tzinfo=timezone.utc)
                if dt < datetime.now(timezone.utc):
                    return None
            except ValueError:
                pass

        # Distance
        distance_miles = 0.0
        distance_raw = raw.get("distance")
        if distance_raw is not None:
            try:
                distance_miles = float(distance_raw)
            except (TypeError, ValueError):
                pass

        # Ticket URL
        ticket_url = raw.get("url", "")

        # Price ranges
        price_min: Optional[float] = None
        price_max: Optional[float] = None
        currency: Optional[str] = None
        price_ranges = raw.get("priceRanges") or []
        if price_ranges:
            pr = price_ranges[0]
            price_min = pr.get("min")
            price_max = pr.get("max")
            currency = pr.get("currency")

        return TicketmasterEvent(
            event_id=event_id,
            event_name=event_name,
            venue_name=venue_name,
            venue_city=venue_city,
            event_date=event_date,
            distance_miles=distance_miles,
            ticket_url=ticket_url,
            price_min=price_min,
            price_max=price_max,
            currency=currency,
            filtered=attraction_mismatch,
        )
    except Exception:
        return None
