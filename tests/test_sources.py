"""Tests for recently_played source."""
from unittest.mock import MagicMock

from src.sources.recently_played import fetch_recently_played_artists, _iso_to_ms


def _make_item(artist_id: str, artist_name: str, played_at: str, track_id: str = "t1"):
    return {
        "track": {
            "id": track_id,
            "artists": [{"id": artist_id, "name": artist_name}],
        },
        "played_at": played_at,
    }


def test_returns_unique_artists():
    sp = MagicMock()
    sp.current_user_recently_played.return_value = {
        "items": [
            _make_item("a1", "Artist One", "2026-03-10T10:00:00.000Z", "t1"),
            _make_item("a2", "Artist Two", "2026-03-10T11:00:00.000Z", "t2"),
            _make_item("a1", "Artist One", "2026-03-10T12:00:00.000Z", "t3"),  # duplicate
        ]
    }
    artists, cursor = fetch_recently_played_artists(sp)
    assert len(artists) == 2
    artist_ids = {a[0] for a in artists}
    assert "a1" in artist_ids
    assert "a2" in artist_ids


def test_returns_cursor_as_newest_timestamp():
    sp = MagicMock()
    sp.current_user_recently_played.return_value = {
        "items": [
            _make_item("a1", "Artist One", "2026-03-10T10:00:00.000Z", "t1"),
            _make_item("a2", "Artist Two", "2026-03-10T12:00:00.000Z", "t2"),
        ]
    }
    _, cursor = fetch_recently_played_artists(sp)
    assert cursor is not None
    # The cursor should correspond to the newest played_at
    expected_ms = _iso_to_ms("2026-03-10T12:00:00.000Z")
    assert cursor == expected_ms


def test_empty_response():
    sp = MagicMock()
    sp.current_user_recently_played.return_value = {"items": []}
    artists, cursor = fetch_recently_played_artists(sp)
    assert artists == []
    assert cursor is None


def test_passes_after_cursor():
    sp = MagicMock()
    sp.current_user_recently_played.return_value = {"items": []}
    fetch_recently_played_artists(sp, after_ms=12345678)
    sp.current_user_recently_played.assert_called_once_with(limit=50, after=12345678)


def test_iso_to_ms():
    ms = _iso_to_ms("2026-03-10T12:00:00.000Z")
    assert ms > 0
    # 2026-03-10T12:00:00 UTC in ms
    from datetime import datetime, timezone
    expected = int(datetime(2026, 3, 10, 12, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)
    assert ms == expected
