"""Tests for the SQLite database layer."""
import pytest
from datetime import datetime, timezone

from src.storage.database import Concert, Database


@pytest.fixture
def db(tmp_path):
    return Database(tmp_path / "test.db")


def _make_concert(**kwargs) -> Concert:
    defaults = dict(
        id="tm_001",
        artist_id="a1",
        artist_name="Artist One",
        event_name="Great Show",
        venue_name="The Venue",
        venue_city="New York, NY",
        event_date="2026-06-01T20:00:00Z",
        distance_miles=42.0,
        ticket_url="https://example.com",
        price_min=45.0,
        price_max=150.0,
        currency="USD",
        first_discovered_at=datetime.now(timezone.utc).isoformat(),
        notified=False,
    )
    defaults.update(kwargs)
    return Concert(**defaults)


class TestArtistOperations:
    def test_upsert_new_artist(self, db):
        is_new = db.upsert_artist("a1", "Artist One", "recently_played")
        assert is_new is True

    def test_upsert_existing_artist(self, db):
        db.upsert_artist("a1", "Artist One", "recently_played")
        is_new = db.upsert_artist("a1", "Artist One", "recently_played")
        assert is_new is False

    def test_get_active_artists(self, db):
        db.upsert_artist("a1", "Artist One", "recently_played")
        db.upsert_artist("a2", "Artist Two", "playlist")
        artists = db.get_active_artists()
        assert len(artists) == 2

    def test_deactivate_artists_not_in(self, db):
        db.upsert_artist("a1", "Artist One", "recently_played")
        db.upsert_artist("a2", "Artist Two", "recently_played")
        db.deactivate_artists_not_in(["a1"])
        artists = db.get_active_artists()
        assert len(artists) == 1
        assert artists[0].id == "a1"

    def test_skip_tm_search_defaults_false(self, db):
        db.upsert_artist("a1", "Artist One", "recently_played")
        artist = db.get_active_artists()[0]
        assert artist.skip_tm_search is False

    def test_set_skip_tm_search_true(self, db):
        db.upsert_artist("a1", "Artist One", "recently_played")
        db.set_skip_tm_search("a1", True)
        artist = db.get_active_artists()[0]
        assert artist.skip_tm_search is True

    def test_set_skip_tm_search_roundtrip(self, db):
        db.upsert_artist("a1", "Artist One", "recently_played")
        db.set_skip_tm_search("a1", True)
        db.set_skip_tm_search("a1", False)
        artist = db.get_active_artists()[0]
        assert artist.skip_tm_search is False

    def test_get_concert_searchable_artists_excludes_skipped(self, db):
        db.upsert_artist("a1", "Artist One", "recently_played")
        db.upsert_artist("a2", "Houses", "playlist")
        db.set_mb_result("a1", True)
        db.set_mb_result("a2", True)
        db.set_skip_tm_search("a2", True)
        searchable = db.get_concert_searchable_artists()
        ids = {a.id for a in searchable}
        assert "a1" in ids
        assert "a2" not in ids

    def test_get_concert_searchable_artists_excludes_mb_inactive(self, db):
        db.upsert_artist("a1", "Artist One", "recently_played")
        db.upsert_artist("a2", "Artist Two", "recently_played")
        db.set_mb_result("a1", True)
        db.set_mb_result("a2", False)  # disbanded
        searchable = db.get_concert_searchable_artists()
        ids = {a.id for a in searchable}
        assert "a1" in ids
        assert "a2" not in ids


class TestPlaylistOperations:
    def test_upsert_new_playlist(self, db):
        changed = db.upsert_playlist("pl1", "My Playlist", "hash_abc")
        assert changed is True

    def test_upsert_same_hash_not_changed(self, db):
        db.upsert_playlist("pl1", "My Playlist", "hash_abc")
        changed = db.upsert_playlist("pl1", "My Playlist", "hash_abc")
        assert changed is False

    def test_upsert_different_hash_changed(self, db):
        db.upsert_playlist("pl1", "My Playlist", "hash_abc")
        changed = db.upsert_playlist("pl1", "My Playlist", "hash_xyz")
        assert changed is True


class TestConcertOperations:
    def test_insert_new_concert(self, db):
        db.upsert_artist("a1", "Artist One", "recently_played")
        is_new = db.insert_concert(_make_concert())
        assert is_new is True

    def test_insert_duplicate_concert(self, db):
        db.upsert_artist("a1", "Artist One", "recently_played")
        db.insert_concert(_make_concert())
        is_new = db.insert_concert(_make_concert())
        assert is_new is False

    def test_get_new_concerts(self, db):
        db.upsert_artist("a1", "Artist One", "recently_played")
        db.insert_concert(_make_concert(id="tm_001"))
        db.insert_concert(_make_concert(id="tm_002"))
        new = db.get_new_concerts()
        assert len(new) == 2

    def test_mark_all_notified(self, db):
        db.upsert_artist("a1", "Artist One", "recently_played")
        db.insert_concert(_make_concert())
        db.mark_all_notified()
        new = db.get_new_concerts()
        assert new == []

    def test_filtered_defaults_false(self, db):
        db.upsert_artist("a1", "Artist One", "recently_played")
        db.insert_concert(_make_concert())
        concerts = db.get_upcoming_concerts()
        assert len(concerts) == 1
        assert concerts[0].filtered is False

    def test_filtered_concert_stored_and_excluded_from_upcoming(self, db):
        db.upsert_artist("a1", "Artist One", "recently_played")
        db.insert_concert(_make_concert(id="tm_good"))
        db.insert_concert(_make_concert(id="tm_tribute", filtered=True))
        upcoming = db.get_upcoming_concerts()
        assert len(upcoming) == 1
        assert upcoming[0].id == "tm_good"

    def test_filtered_concert_preserved_in_db(self, db):
        """Filtered concerts must remain in the DB (not deleted), just excluded from upcoming."""
        db.upsert_artist("a1", "Artist One", "recently_played")
        db.insert_concert(_make_concert(id="tm_tribute", filtered=True))
        # insert_concert should return True (it IS stored)
        # and get_upcoming_concerts should return empty
        upcoming = db.get_upcoming_concerts()
        assert upcoming == []
        # Verify it's actually in the DB by re-inserting — should return False (already exists)
        is_new = db.insert_concert(_make_concert(id="tm_tribute", filtered=True))
        assert is_new is False


class TestMonitoringState:
    def test_set_and_get_state(self, db):
        db.set_state("cursor", "12345")
        assert db.get_state("cursor") == "12345"

    def test_get_missing_returns_default(self, db):
        assert db.get_state("nonexistent") is None
        assert db.get_state("nonexistent", "fallback") == "fallback"

    def test_overwrite_state(self, db):
        db.set_state("key", "v1")
        db.set_state("key", "v2")
        assert db.get_state("key") == "v2"
