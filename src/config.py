"""
Config loading and validation.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

import yaml


@dataclass
class SpotifyConfig:
    client_id: str
    client_secret: str
    redirect_uri: str = "http://localhost:8888/callback"


@dataclass
class TicketmasterConfig:
    api_key: str


@dataclass
class LocationConfig:
    address: str
    radius_miles: int = 100


@dataclass
class MonitoringConfig:
    recently_played_interval_minutes: int = 60
    playlist_interval_minutes: int = 360
    concert_search_interval_minutes: int = 720


@dataclass
class OutputConfig:
    events_file: str = "data/events.json"
    log_level: str = "INFO"


@dataclass
class AppConfig:
    spotify: SpotifyConfig
    ticketmaster: TicketmasterConfig
    location: LocationConfig
    monitoring: MonitoringConfig
    output: OutputConfig
    playlists: List[str] = field(default_factory=list)
    skip_artists: List[str] = field(default_factory=list)  # artist names to exclude from TM searches


def load_config(path: str | Path = "config.yaml") -> AppConfig:
    """Load and validate configuration from YAML file."""
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path.resolve()}")

    with open(config_path) as f:
        raw = yaml.safe_load(f)

    # Spotify
    sp = raw.get("spotify", {})
    spotify = SpotifyConfig(
        client_id=os.environ.get("SPOTIFY_CLIENT_ID") or sp.get("client_id", ""),
        client_secret=os.environ.get("SPOTIFY_CLIENT_SECRET") or sp.get("client_secret", ""),
        redirect_uri=sp.get("redirect_uri", "http://localhost:8888/callback"),
    )
    _require(spotify.client_id, "spotify.client_id")
    _require(spotify.client_secret, "spotify.client_secret")

    # Ticketmaster
    tm = raw.get("ticketmaster", {})
    ticketmaster = TicketmasterConfig(
        api_key=os.environ.get("TICKETMASTER_API_KEY") or tm.get("api_key", ""),
    )
    _require(ticketmaster.api_key, "ticketmaster.api_key")

    # Location
    loc = raw.get("location", {})
    location = LocationConfig(
        address=loc.get("address", ""),
        radius_miles=int(loc.get("radius_miles", 100)),
    )
    _require(location.address, "location.address")

    # Playlists — filter out empty/placeholder entries
    raw_playlists = raw.get("playlists", []) or []
    playlists = [p for p in raw_playlists if p and p.strip()]

    # Skip artists — artist names to exclude from Ticketmaster searches
    raw_skip = raw.get("skip_artists", []) or []
    skip_artists = [s for s in raw_skip if s and s.strip()]

    # Monitoring
    mon = raw.get("monitoring", {})
    monitoring = MonitoringConfig(
        recently_played_interval_minutes=int(mon.get("recently_played_interval_minutes", 60)),
        playlist_interval_minutes=int(mon.get("playlist_interval_minutes", 360)),
        concert_search_interval_minutes=int(mon.get("concert_search_interval_minutes", 720)),
    )

    # Output
    out = raw.get("output", {})
    output = OutputConfig(
        events_file=out.get("events_file", "data/events.json"),
        log_level=out.get("log_level", "INFO").upper(),
    )

    return AppConfig(
        spotify=spotify,
        ticketmaster=ticketmaster,
        location=location,
        monitoring=monitoring,
        output=output,
        playlists=playlists,
        skip_artists=skip_artists,
    )


def _require(value: str, field_name: str) -> None:
    if not value or value.startswith("YOUR_"):
        raise ValueError(
            f"Missing or placeholder value for '{field_name}' in config.yaml. "
            "Please set a real value or use the corresponding environment variable."
        )
