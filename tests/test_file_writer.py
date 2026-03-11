"""Tests for file_writer deduplication and output structure."""
import json
from datetime import datetime, timezone

import pytest

from src.output.file_writer import _deduplicate, write_events_file
from src.storage.database import Concert, Database


def _make_concert(**kwargs) -> Concert:
    defaults = dict(
        id="tm_001",
        artist_id="a1",
        artist_name="Artist One",
        event_name="Great Show",
        venue_name="The Venue",
        venue_city="Boston, MA",
        event_date="2026-06-01T20:00:00Z",
        distance_miles=42.0,
        ticket_url="https://example.com",
        price_min=None,
        price_max=None,
        currency=None,
        first_discovered_at=datetime.now(timezone.utc).isoformat(),
        notified=False,
    )
    defaults.update(kwargs)
    return Concert(**defaults)


class TestDeduplicate:
    def test_no_duplicates_unchanged(self):
        concerts = [
            _make_concert(id="e1", event_date="2026-06-01T20:00:00Z"),
            _make_concert(id="e2", artist_id="a2", artist_name="Artist Two", event_date="2026-06-02T20:00:00Z"),
        ]
        result = _deduplicate(concerts)
        assert len(result) == 2

    def test_removes_same_artist_venue_date(self):
        # Two different TM event IDs, same artist/venue/date → keep first
        concerts = [
            _make_concert(id="e1", event_name="GA Tickets"),
            _make_concert(id="e2", event_name="VIP Package"),
        ]
        result = _deduplicate(concerts)
        assert len(result) == 1
        assert result[0].id == "e1"

    def test_different_dates_kept(self):
        concerts = [
            _make_concert(id="e1", event_date="2026-06-01T20:00:00Z"),
            _make_concert(id="e2", event_date="2026-06-02T20:00:00Z"),
        ]
        result = _deduplicate(concerts)
        assert len(result) == 2

    def test_different_venues_kept(self):
        concerts = [
            _make_concert(id="e1", venue_name="Venue A"),
            _make_concert(id="e2", venue_name="Venue B"),
        ]
        result = _deduplicate(concerts)
        assert len(result) == 2

    def test_different_artists_kept(self):
        concerts = [
            _make_concert(id="e1", artist_id="a1"),
            _make_concert(id="e2", artist_id="a2"),
        ]
        result = _deduplicate(concerts)
        assert len(result) == 2

    def test_date_only_comparison(self):
        # Same date, different times → treated as same show
        concerts = [
            _make_concert(id="e1", event_date="2026-06-01T19:00:00Z"),
            _make_concert(id="e2", event_date="2026-06-01T20:00:00Z"),
        ]
        result = _deduplicate(concerts)
        assert len(result) == 1

    def test_empty_list(self):
        assert _deduplicate([]) == []


class TestWriteEventsFile:
    def test_writes_valid_json(self, tmp_path):
        db = Database(tmp_path / "test.db")
        output = str(tmp_path / "events.json")
        write_events_file(db, output)
        data = json.loads((tmp_path / "events.json").read_text())
        assert "last_updated" in data
        assert "summary" in data
        assert "all_upcoming_concerts" in data
        assert "new_events" in data
        assert "tracked_artists" in data

    def test_deduplication_reflected_in_output(self, tmp_path):
        db = Database(tmp_path / "test.db")
        db.upsert_artist("a1", "Artist One", "recently_played")
        # Insert two concerts with same artist/venue/date but different IDs
        db.insert_concert(_make_concert(id="e1", event_name="GA Tickets"))
        db.insert_concert(_make_concert(id="e2", event_name="VIP Package"))

        output = str(tmp_path / "events.json")
        write_events_file(db, output)
        data = json.loads((tmp_path / "events.json").read_text())

        assert data["summary"]["total_upcoming_concerts"] == 1
        assert len(data["all_upcoming_concerts"]) == 1
        assert data["all_upcoming_concerts"][0]["event_id"] == "e1"

    def test_is_new_flag_set_on_first_write(self, tmp_path):
        db = Database(tmp_path / "test.db")
        db.upsert_artist("a1", "Artist One", "recently_played")
        db.insert_concert(_make_concert(id="e1"))

        output = str(tmp_path / "events.json")
        write_events_file(db, output)
        data = json.loads((tmp_path / "events.json").read_text())

        assert data["all_upcoming_concerts"][0]["is_new"] is True

    def test_is_new_flag_cleared_on_second_write(self, tmp_path):
        db = Database(tmp_path / "test.db")
        db.upsert_artist("a1", "Artist One", "recently_played")
        db.insert_concert(_make_concert(id="e1"))

        output = str(tmp_path / "events.json")
        write_events_file(db, output)   # first write — marks notified
        write_events_file(db, output)   # second write — e1 is now old
        data = json.loads((tmp_path / "events.json").read_text())

        assert data["all_upcoming_concerts"][0]["is_new"] is False
        assert data["summary"]["new_since_last_check"] == 0
