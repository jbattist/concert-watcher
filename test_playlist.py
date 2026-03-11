"""
Two-step Spotify auth + playlist test.

Step 1 — Get the auth URL:
    .venv/bin/python test_playlist.py

Step 2 — After authorizing in your browser, your browser will try to load
    localhost:8888/callback?code=... and show a "can't connect" error.
    Copy that full URL from the address bar and pass it as an argument:

    .venv/bin/python test_playlist.py "http://localhost:8888/callback?code=AQ..."
"""
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import yaml

sys.path.insert(0, str(Path(__file__).parent))

from src.auth.spotify_oauth import SCOPES, validate_auth
from src.config import SpotifyConfig
from src.sources.playlists import fetch_playlist_artists

import spotipy
from spotipy.oauth2 import SpotifyOAuth

# ------------------------------------------------------------------ #
# Load config (Ticketmaster key not required for this test)
# ------------------------------------------------------------------ #
with open("config.yaml") as f:
    raw = yaml.safe_load(f)

sp_raw = raw["spotify"]
config_spotify = SpotifyConfig(
    client_id=sp_raw["client_id"],
    client_secret=sp_raw["client_secret"],
    redirect_uri=sp_raw.get("redirect_uri", "http://localhost:8888/callback"),
)
playlists = [p for p in (raw.get("playlists") or []) if p and p.strip()]

# ------------------------------------------------------------------ #
# Auth
# ------------------------------------------------------------------ #
auth_manager = SpotifyOAuth(
    client_id=config_spotify.client_id,
    client_secret=config_spotify.client_secret,
    redirect_uri=config_spotify.redirect_uri,
    scope=SCOPES,
    cache_path=".spotify_cache",
    open_browser=False,
)

# Check for a valid cached token first
token_info = auth_manager.get_cached_token()
if token_info and not auth_manager.is_token_expired(token_info):
    print("Using cached Spotify token.")
    sp = spotipy.Spotify(auth_manager=auth_manager)

elif len(sys.argv) > 1:
    # Step 2: user passed the redirect URL
    redirect_url = sys.argv[1]
    parsed = urlparse(redirect_url)
    params = parse_qs(parsed.query)
    code = params.get("code", [None])[0]
    if not code:
        print(f"ERROR: no 'code' parameter found in the URL: {redirect_url}", file=sys.stderr)
        sys.exit(1)
    auth_manager.get_access_token(code, as_dict=False, check_cache=False)
    print("Token saved to .spotify_cache")
    sp = spotipy.Spotify(auth_manager=auth_manager)

else:
    # Step 1: print the auth URL and exit
    auth_url = auth_manager.get_authorize_url()
    print("\nStep 1 — Open this URL in your browser:\n")
    print(f"  {auth_url}")
    print("\nAfter you authorize, your browser will try to load localhost:8888")
    print("and show a connection error. That is expected.")
    print("\nCopy the FULL URL from the browser address bar (it will look like:")
    print("  http://localhost:8888/callback?code=AQxxxxxx...)")
    print("\nThen run:")
    print('  .venv/bin/python test_playlist.py "<paste the full URL here>"\n')
    sys.exit(0)

# ------------------------------------------------------------------ #
# Fetch playlists
# ------------------------------------------------------------------ #
username = validate_auth(sp)
print(f"Logged in as: {username}\n")

for uri in playlists:
    print(f"Fetching playlist: {uri}")
    playlist_id, name, artists, content_hash = fetch_playlist_artists(sp, uri)
    print(f"  Name:           {name}")
    print(f"  Artists found:  {len(artists)}")
    print(f"  Content hash:   {content_hash}")
    print(f"  First 10 artists:")
    for artist_id, artist_name in artists[:10]:
        print(f"    - {artist_name}  ({artist_id})")
    if len(artists) > 10:
        print(f"    ... and {len(artists) - 10} more")
    print()
