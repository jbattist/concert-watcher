"""
Fetch tracks from configured Spotify playlists and extract unique artists.
Uses content hashing to detect changes and avoid unnecessary processing.
"""
from __future__ import annotations

import hashlib
from typing import Dict, List, Optional, Tuple

import spotipy


def fetch_playlist_artists(
    sp: spotipy.Spotify,
    playlist_uri: str,
) -> Tuple[str, str, List[Tuple[str, str]], str]:
    """
    Fetch all tracks in a playlist and extract unique artists.

    Args:
        sp:           Authenticated Spotify client.
        playlist_uri: Spotify playlist URI (e.g. "spotify:playlist:abc123").

    Returns:
        A tuple of:
          - playlist_id   (str)
          - playlist_name (str)
          - artists       List of unique (artist_id, artist_name) tuples
          - content_hash  SHA-256 of sorted track+artist IDs for change detection
    """
    playlist_id = _uri_to_id(playlist_uri)

    # Fetch playlist metadata
    meta = sp.playlist(playlist_id, fields="id,name")
    playlist_name: str = (meta or {}).get("name", playlist_id)

    # Paginate through all tracks
    all_track_artist_ids: List[str] = []
    seen: Dict[str, str] = {}  # artist_id -> artist_name
    offset = 0
    limit = 100

    while True:
        page = sp.playlist_tracks(
            playlist_id,
            fields="items(track(id,artists(id,name))),next",
            limit=limit,
            offset=offset,
        )
        items = (page or {}).get("items") or []

        for item in items:
            track = (item or {}).get("track") or {}
            track_id = track.get("id") or ""
            for artist in track.get("artists") or []:
                artist_id = artist.get("id")
                artist_name = artist.get("name")
                if artist_id and artist_name:
                    all_track_artist_ids.append(f"{track_id}:{artist_id}")
                    if artist_id not in seen:
                        seen[artist_id] = artist_name

        if not (page or {}).get("next"):
            break
        offset += limit

    content_hash = _hash_ids(sorted(all_track_artist_ids))
    return playlist_id, playlist_name, list(seen.items()), content_hash


def _uri_to_id(uri: str) -> str:
    """Convert a Spotify URI or plain ID to just the ID."""
    # e.g. "spotify:playlist:abc123" -> "abc123"
    # or bare "abc123" -> "abc123"
    parts = uri.split(":")
    return parts[-1]


def _hash_ids(ids: List[str]) -> str:
    """Return a short SHA-256 hex digest of a list of IDs."""
    combined = "|".join(ids)
    return hashlib.sha256(combined.encode()).hexdigest()[:16]
