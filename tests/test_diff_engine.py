"""Tests for the diff engine."""
import pytest

from src.monitoring.diff_engine import process_artist_batch
from src.storage.database import Database


@pytest.fixture
def db(tmp_path):
    return Database(tmp_path / "test.db")


def test_new_artist_is_returned(db):
    new = process_artist_batch(db, [("a1", "Artist One")], source="recently_played")
    assert len(new) == 1
    assert new[0] == ("a1", "Artist One")


def test_existing_artist_not_returned_as_new(db):
    process_artist_batch(db, [("a1", "Artist One")], source="recently_played")
    new = process_artist_batch(db, [("a1", "Artist One")], source="recently_played")
    assert new == []


def test_multiple_artists_only_new_ones_returned(db):
    process_artist_batch(db, [("a1", "Artist One")], source="recently_played")
    new = process_artist_batch(
        db,
        [("a1", "Artist One"), ("a2", "Artist Two"), ("a3", "Artist Three")],
        source="recently_played",
    )
    assert len(new) == 2
    ids = {a[0] for a in new}
    assert ids == {"a2", "a3"}


def test_source_merge_to_both(db):
    process_artist_batch(db, [("a1", "Artist One")], source="recently_played")
    process_artist_batch(db, [("a1", "Artist One")], source="playlist")
    artists = db.get_active_artists()
    assert artists[0].source == "both"


def test_empty_batch(db):
    new = process_artist_batch(db, [], source="recently_played")
    assert new == []
