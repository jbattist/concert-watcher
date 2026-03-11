"""
Tests for the MusicBrainz client and the run_mb_checks diff-engine helper.
"""
from unittest.mock import MagicMock, patch

import pytest

from src.concerts.musicbrainz import MusicBrainzClient
from src.monitoring.diff_engine import run_mb_checks
from src.storage.database import Database


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _search_response(mbid: str, score: int = 95) -> dict:
    return {"artists": [{"id": mbid, "score": score}]}


def _artist_response(ended: bool | str | None) -> dict:
    return {"life-span": {"ended": ended}}


@pytest.fixture
def db(tmp_path):
    return Database(tmp_path / "test.db")


@pytest.fixture
def mb():
    return MusicBrainzClient()


# ---------------------------------------------------------------------------
# MusicBrainzClient.is_artist_active
# ---------------------------------------------------------------------------

class TestIsArtistActive:
    def _mock_get(self, search_data: dict, artist_data: dict):
        """Return a side_effect list for two sequential requests.get calls."""
        def _make_resp(data):
            r = MagicMock()
            r.status_code = 200
            r.json.return_value = data
            return r

        return [_make_resp(search_data), _make_resp(artist_data)]

    def test_active_artist_returns_true(self, mb):
        responses = self._mock_get(
            _search_response("mbid-001"),
            _artist_response(ended=False),
        )
        with patch.object(mb._session, "get", side_effect=responses):
            assert mb.is_artist_active("Radiohead") is True

    def test_ended_artist_returns_false(self, mb):
        responses = self._mock_get(
            _search_response("mbid-002"),
            _artist_response(ended=True),
        )
        with patch.object(mb._session, "get", side_effect=responses):
            assert mb.is_artist_active("The Beatles") is False

    def test_ended_string_true_returns_false(self, mb):
        responses = self._mock_get(
            _search_response("mbid-003"),
            _artist_response(ended="true"),
        )
        with patch.object(mb._session, "get", side_effect=responses):
            assert mb.is_artist_active("Old Band") is False

    def test_ended_string_false_returns_true(self, mb):
        responses = self._mock_get(
            _search_response("mbid-004"),
            _artist_response(ended="false"),
        )
        with patch.object(mb._session, "get", side_effect=responses):
            assert mb.is_artist_active("Active Band") is True

    def test_absent_life_span_assumes_active(self, mb):
        responses = self._mock_get(
            _search_response("mbid-005"),
            {"life-span": {}},  # 'ended' key missing
        )
        with patch.object(mb._session, "get", side_effect=responses):
            assert mb.is_artist_active("Unknown Status") is True

    def test_no_confident_match_assumes_active(self, mb):
        low_score_response = {"artists": [{"id": "mbid-006", "score": 50}]}
        r = MagicMock()
        r.status_code = 200
        r.json.return_value = low_score_response
        with patch.object(mb._session, "get", return_value=r):
            assert mb.is_artist_active("Obscure Artist") is True

    def test_no_results_assumes_active(self, mb):
        r = MagicMock()
        r.status_code = 200
        r.json.return_value = {"artists": []}
        with patch.object(mb._session, "get", return_value=r):
            assert mb.is_artist_active("No Results Artist") is True

    def test_search_http_error_assumes_active(self, mb):
        r = MagicMock()
        r.status_code = 503
        with patch.object(mb._session, "get", return_value=r):
            assert mb.is_artist_active("Network Error Artist") is True

    def test_detail_http_error_assumes_active(self, mb):
        search_r = MagicMock()
        search_r.status_code = 200
        search_r.json.return_value = _search_response("mbid-007")
        detail_r = MagicMock()
        detail_r.status_code = 404
        with patch.object(mb._session, "get", side_effect=[search_r, detail_r]):
            assert mb.is_artist_active("Detail Error Artist") is True


# ---------------------------------------------------------------------------
# run_mb_checks (diff_engine integration)
# ---------------------------------------------------------------------------

class TestRunMbChecks:
    def test_marks_active_artist_as_checked(self, db):
        db.upsert_artist("a1", "Active Band", "recently_played")
        mb = MusicBrainzClient()
        mb.is_artist_active = MagicMock(return_value=True)

        checked, skipped = run_mb_checks(db, mb)

        assert checked == 1
        assert skipped == 0
        artist = db.get_active_artists()[0]
        assert artist.mb_checked is True
        assert artist.mb_active is True

    def test_marks_ended_artist_as_inactive(self, db):
        db.upsert_artist("a2", "Disbanded Band", "recently_played")
        mb = MusicBrainzClient()
        mb.is_artist_active = MagicMock(return_value=False)

        checked, skipped = run_mb_checks(db, mb)

        assert checked == 1
        assert skipped == 1
        # Artist should still appear in get_active_artists (mb_active flag only
        # affects concert searches), but mb_active should be False
        artists = db.get_active_artists()
        assert artists[0].mb_active is False

    def test_already_checked_artists_are_skipped(self, db):
        db.upsert_artist("a3", "Already Checked", "recently_played")
        db.set_mb_result("a3", mb_active=True)

        mb = MusicBrainzClient()
        mb.is_artist_active = MagicMock(return_value=True)

        checked, skipped = run_mb_checks(db, mb)

        assert checked == 0
        mb.is_artist_active.assert_not_called()

    def test_exception_leaves_artist_unchecked(self, db):
        db.upsert_artist("a4", "Error Artist", "recently_played")
        mb = MusicBrainzClient()
        mb.is_artist_active = MagicMock(side_effect=RuntimeError("network"))

        checked, skipped = run_mb_checks(db, mb)

        assert checked == 0
        assert skipped == 0
        # mb_checked should still be 0 so we retry next run
        artist = db.get_artists_needing_mb_check()
        assert len(artist) == 1

    def test_get_concert_searchable_excludes_ended(self, db):
        db.upsert_artist("a5", "Active Artist", "recently_played")
        db.upsert_artist("a6", "Ended Artist", "recently_played")
        db.set_mb_result("a5", mb_active=True)
        db.set_mb_result("a6", mb_active=False)

        searchable = db.get_concert_searchable_artists()
        ids = {a.id for a in searchable}
        assert "a5" in ids
        assert "a6" not in ids

    def test_unchecked_artists_are_searchable(self, db):
        """Artists with mb_checked=False are still included in searchable (optimistic)."""
        db.upsert_artist("a7", "New Artist", "recently_played")
        # No mb check performed yet — mb_active defaults to True

        searchable = db.get_concert_searchable_artists()
        assert any(a.id == "a7" for a in searchable)
