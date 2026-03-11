"""
Spotify OAuth2 authentication — browser-based flow with token persistence.
"""
from __future__ import annotations

from pathlib import Path

import spotipy
from spotipy.oauth2 import SpotifyOAuth

from src.config import SpotifyConfig

# Scopes required by the app
SCOPES = " ".join([
    "user-read-recently-played",
    "playlist-read-private",
    "playlist-read-collaborative",
])


def create_spotify_client(config: SpotifyConfig, cache_path: str | Path = ".spotify_cache") -> spotipy.Spotify:
    """
    Create an authenticated Spotify client.

    On first run this opens a browser window for the user to authorize the app.
    The resulting token is saved to `cache_path` and auto-refreshed on subsequent runs.
    """
    auth_manager = SpotifyOAuth(
        client_id=config.client_id,
        client_secret=config.client_secret,
        redirect_uri=config.redirect_uri,
        scope=SCOPES,
        cache_path=str(cache_path),
        open_browser=False,
    )
    return spotipy.Spotify(auth_manager=auth_manager)


def validate_auth(sp: spotipy.Spotify) -> str:
    """
    Validate that authentication is working by fetching the current user.
    Returns the Spotify username.
    """
    user = sp.current_user()
    if user is None:
        raise RuntimeError("Spotify authentication failed: could not fetch current user.")
    return user.get("display_name") or user.get("id") or "unknown"
