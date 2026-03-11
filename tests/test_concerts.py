"""Tests for Ticketmaster client."""
from unittest.mock import MagicMock, patch

import pytest

from src.concerts.ticketmaster import TicketmasterClient, _attraction_matches_artist, _parse_event


def _make_raw_event(
    event_id="tm_123",
    name="Test Concert",
    venue_name="Test Venue",
    city="Boston",
    state="MA",
    date="2026-05-15T20:00:00Z",
    distance=42.0,
    url="https://ticketmaster.com/event/tm_123",
    price_min=45.0,
    price_max=150.0,
    attractions=None,   # list of {"name": ...} dicts, or None to omit
):
    raw = {
        "id": event_id,
        "name": name,
        "url": url,
        "distance": distance,
        "dates": {"start": {"dateTime": date}},
        "_embedded": {
            "venues": [{
                "name": venue_name,
                "city": {"name": city},
                "state": {"stateCode": state},
            }]
        },
        "priceRanges": [{"min": price_min, "max": price_max, "currency": "USD"}],
    }
    if attractions is not None:
        raw["_embedded"]["attractions"] = attractions
    return raw


class TestAttractionMatchesArtist:
    def test_exact_match(self):
        assert _attraction_matches_artist("Lady Gaga", "Lady Gaga") is True

    def test_case_insensitive(self):
        assert _attraction_matches_artist("lady gaga", "LADY GAGA") is True

    def test_attraction_is_superset(self):
        # "Dave Matthews Band" should match search for "Dave Matthews"
        assert _attraction_matches_artist("Dave Matthews", "Dave Matthews Band") is True

    def test_artist_is_superset(self):
        # searching "Dave Matthews Band" and attraction is "Dave Matthews"
        assert _attraction_matches_artist("Dave Matthews Band", "Dave Matthews") is True

    def test_tribute_band_rejected(self):
        assert _attraction_matches_artist("Lady Gaga", "Haus Of Monsters- A Lady Gaga Tribute") is False

    def test_tribute_band_rejected_chris_stapleton(self):
        assert _attraction_matches_artist("Chris Stapleton", "Traveller- The Chris Stapleton Experience") is False

    def test_different_artist_rejected(self):
        assert _attraction_matches_artist("Zach Bryan", "Luke Bryan") is False

    def test_punctuation_stripped(self):
        assert _attraction_matches_artist("fun.", "fun.") is True


class TestParseEvent:
    def test_parses_full_event(self):
        raw = _make_raw_event(attractions=[{"name": "Test Artist"}])
        evt = _parse_event(raw, "Test Artist")
        assert evt is not None
        assert evt.event_id == "tm_123"
        assert evt.event_name == "Test Concert"
        assert evt.venue_name == "Test Venue"
        assert evt.venue_city == "Boston, MA"
        assert evt.distance_miles == 42.0
        assert evt.price_min == 45.0
        assert evt.price_max == 150.0
        assert evt.currency == "USD"

    def test_returns_none_for_missing_id(self):
        raw = _make_raw_event()
        raw["id"] = None
        assert _parse_event(raw, "Test Artist") is None

    def test_returns_none_for_past_event(self):
        raw = _make_raw_event(date="2020-01-01T20:00:00Z")
        assert _parse_event(raw, "Test Artist") is None

    def test_handles_no_price_range(self):
        raw = _make_raw_event(attractions=[{"name": "Test Artist"}])
        raw.pop("priceRanges", None)
        evt = _parse_event(raw, "Test Artist")
        assert evt is not None
        assert evt.price_min is None
        assert evt.price_max is None

    def test_handles_no_venue(self):
        raw = _make_raw_event(attractions=[{"name": "Test Artist"}])
        raw["_embedded"]["venues"] = []
        evt = _parse_event(raw, "Test Artist")
        assert evt is not None
        assert evt.venue_name == "Unknown Venue"

    def test_handles_no_distance(self):
        raw = _make_raw_event(attractions=[{"name": "Test Artist"}])
        raw.pop("distance", None)
        evt = _parse_event(raw, "Test Artist")
        assert evt is not None
        assert evt.distance_miles == 0.0

    def test_handles_local_date_only(self):
        raw = _make_raw_event(attractions=[{"name": "Test Artist"}])
        raw["dates"] = {"start": {"localDate": "2026-06-01"}}
        evt = _parse_event(raw, "Test Artist")
        assert evt is not None
        assert evt.event_date == "2026-06-01"

    def test_no_attractions_passes_through(self):
        # Events without attractions listed are accepted (benefit of the doubt)
        raw = _make_raw_event()  # no attractions key
        evt = _parse_event(raw, "Test Artist")
        assert evt is not None
        assert evt.filtered is False

    def test_tribute_band_rejected_by_attraction(self):
        raw = _make_raw_event(
            name="Haus Of Monsters- A Lady Gaga Tribute",
            attractions=[{"name": "Haus Of Monsters"}],
        )
        evt = _parse_event(raw, "Lady Gaga")
        assert evt is not None
        assert evt.filtered is True

    def test_supporting_act_accepted(self):
        # Artist is listed as an attraction even though they don't headline
        raw = _make_raw_event(
            name="Young the Giant - Victory Garden Tour with Cold War Kids",
            attractions=[{"name": "Young the Giant"}, {"name": "Cold War Kids"}],
        )
        evt = _parse_event(raw, "Cold War Kids")
        assert evt is not None
        assert evt.filtered is False


class TestTicketmasterClient:
    def test_search_returns_events(self):
        client = TicketmasterClient("fake_key")
        mock_response = {
            "_embedded": {"events": [_make_raw_event(attractions=[{"name": "Test Artist"}])]},
            "page": {"totalPages": 1},
        }
        with patch("requests.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = mock_response
            mock_get.return_value = mock_resp

            results = client.search_events("Test Artist", 42.36, -71.06, radius_miles=100)
        assert len(results) == 1
        assert results[0].event_id == "tm_123"

    def test_search_returns_empty_on_404(self):
        client = TicketmasterClient("fake_key")
        with patch("requests.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 404
            mock_get.return_value = mock_resp

            results = client.search_events("Unknown Artist", 42.36, -71.06)
        assert results == []

    def test_deduplicates_events_across_pages(self):
        client = TicketmasterClient("fake_key")
        page1 = {
            "_embedded": {"events": [
                _make_raw_event("e1", attractions=[{"name": "Test Artist"}]),
                _make_raw_event("e2", attractions=[{"name": "Test Artist"}]),
            ]},
            "page": {"totalPages": 2},
        }
        page2 = {
            "_embedded": {"events": [
                _make_raw_event("e2", attractions=[{"name": "Test Artist"}]),
                _make_raw_event("e3", attractions=[{"name": "Test Artist"}]),
            ]},
            "page": {"totalPages": 2},
        }
        with patch("requests.get") as mock_get:
            mock_resp1, mock_resp2 = MagicMock(), MagicMock()
            mock_resp1.status_code = 200
            mock_resp1.json.return_value = page1
            mock_resp2.status_code = 200
            mock_resp2.json.return_value = page2
            mock_get.side_effect = [mock_resp1, mock_resp2]

            results = client.search_events("Test Artist", 42.36, -71.06, max_pages=3)
        ids = {r.event_id for r in results}
        assert ids == {"e1", "e2", "e3"}

    def test_raises_on_invalid_key(self):
        client = TicketmasterClient("bad_key")
        with patch("requests.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 401
            mock_get.return_value = mock_resp

            with pytest.raises(ValueError, match="invalid or expired"):
                client.search_events("Artist", 42.36, -71.06)

    def test_tribute_filtered_by_search(self):
        client = TicketmasterClient("fake_key")
        mock_response = {
            "_embedded": {"events": [
                _make_raw_event(
                    name="Haus Of Monsters- A Lady Gaga Tribute",
                    attractions=[{"name": "Haus Of Monsters"}],
                )
            ]},
            "page": {"totalPages": 1},
        }
        with patch("requests.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = mock_response
            mock_get.return_value = mock_resp

            results = client.search_events("Lady Gaga", 42.36, -71.06)
        assert len(results) == 1
        assert results[0].filtered is True
