"""
Address geocoding — converts a human-readable address to lat/lng coordinates.
Uses Nominatim (OpenStreetMap) via geopy. Result is cached in the database.
"""
from __future__ import annotations

from typing import Optional, Tuple

from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderServiceError

_APP_USER_AGENT = "concert-watcher/1.0"

# State keys for the cached geocode result
_LAT_KEY = "geocode_lat"
_LNG_KEY = "geocode_lng"
_ADDR_KEY = "geocode_address"


def geocode_address(address: str) -> Tuple[float, float]:
    """
    Convert an address string to (latitude, longitude).

    Raises:
        ValueError: if the address cannot be geocoded.
        GeocoderTimedOut / GeocoderServiceError: on transient failures.
    """
    geolocator = Nominatim(user_agent=_APP_USER_AGENT)
    location = geolocator.geocode(address, timeout=10)
    if location is None:
        raise ValueError(
            f"Could not geocode address: '{address}'. "
            "Please check the address in config.yaml."
        )
    return location.latitude, location.longitude


def get_or_cache_coordinates(
    address: str,
    db_get: callable,  # type: ignore[type-arg]
    db_set: callable,  # type: ignore[type-arg]
) -> Tuple[float, float]:
    """
    Return cached lat/lng if the address matches what's stored, otherwise
    geocode and persist. This avoids calling Nominatim on every startup.

    Args:
        address: The address string from config.
        db_get:  Database.get_state callable.
        db_set:  Database.set_state callable.
    """
    cached_addr = db_get(_ADDR_KEY)
    if cached_addr == address:
        lat = db_get(_LAT_KEY)
        lng = db_get(_LNG_KEY)
        if lat is not None and lng is not None:
            return float(lat), float(lng)

    # Geocode and persist
    lat, lng = geocode_address(address)
    db_set(_ADDR_KEY, address)
    db_set(_LAT_KEY, str(lat))
    db_set(_LNG_KEY, str(lng))
    return lat, lng
