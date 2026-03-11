"""One-shot Ticketmaster search — run manually to refresh concert data."""
import logging
import sqlite3
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    stream=sys.stdout,
    force=True,
)
log = logging.getLogger(__name__)

from src.config import load_config
from src.concerts.geocoding import get_or_cache_coordinates
from src.concerts.musicbrainz import MusicBrainzClient
from src.concerts.ticketmaster import TicketmasterClient
from src.monitoring.diff_engine import run_mb_checks, search_and_store_concerts
from src.output.file_writer import write_events_file
from src.storage.database import Database

config = load_config("config.yaml")
db     = Database("data/tracker.db")
tm     = TicketmasterClient(api_key=config.ticketmaster.api_key)
mb     = MusicBrainzClient()

lat, lng = get_or_cache_coordinates(config.location.address, db.get_state, db.set_state)

checked, skipped = run_mb_checks(db, mb)
if checked:
    log.info(f"MB: checked={checked}, skipped={skipped}")

searchable    = db.get_concert_searchable_artists()
artist_tuples = [(a.id, a.name) for a in searchable]
log.info(f"Searching Ticketmaster for {len(artist_tuples)} artists...")

new_ids = search_and_store_concerts(
    db, tm, artist_tuples,
    lat=lat, lng=lng,
    radius_miles=config.location.radius_miles,
)
log.info(f"Search complete — {len(new_ids)} new event(s) stored")

conn = sqlite3.connect("data/tracker.db")
real    = conn.execute("SELECT COUNT(*) FROM concerts WHERE event_date >= date('now') AND filtered=0").fetchone()[0]
flagged = conn.execute("SELECT COUNT(*) FROM concerts WHERE event_date >= date('now') AND filtered=1").fetchone()[0]
conn.close()
log.info(f"DB: {real} upcoming concerts, {flagged} flagged/filtered")

write_events_file(db, config.output.events_file)
log.info(f"events.json updated")
