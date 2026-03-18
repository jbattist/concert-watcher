# concert-watcher

A Python daemon that monitors your Spotify listening history, extracts artists, and searches for upcoming live concerts near you via the Ticketmaster API. Results are exposed via a local web UI and an `events.json` file.

## Features

- Tracks artists from Spotify recently-played history and configured playlists
- Searches Ticketmaster for upcoming concerts within a configurable radius
- Filters out tribute bands and cover shows via attraction validation
- Flags disbanded artists via MusicBrainz lookups
- Dracula-themed web UI at `http://localhost:7474` with sortable columns and live search
- Background APScheduler daemon with configurable poll intervals
- SQLite storage with full concert history

## Requirements

- Python 3.10+
- A [Spotify Developer](https://developer.spotify.com/dashboard) app (free)
- A [Ticketmaster Developer](https://developer.ticketmaster.com/) API key (free)

## Setup

### 1. Clone and create virtualenv

```bash
git clone https://github.com/YOUR_USERNAME/concert-watcher.git
cd concert-watcher
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

### 2. Configure

```bash
cp config.yaml.example config.yaml
```

Edit `config.yaml` and fill in:

| Key | Where to get it |
|-----|----------------|
| `spotify.client_id` | Spotify Developer Dashboard → your app → Settings |
| `spotify.client_secret` | Spotify Developer Dashboard → your app → Settings |
| `spotify.redirect_uri` | Must match what you set in the Spotify app (default: `http://127.0.0.1:8888/callback`) |
| `ticketmaster.api_key` | [Ticketmaster Developer Portal](https://developer.ticketmaster.com/) → My Apps |
| `location.address` | Your city or address (e.g. `"Boston, MA"`) |
| `playlists` | Spotify playlist URIs to track (e.g. `spotify:playlist:37i9dQZF1DXcBWIGoYBM5M`) |

**In your Spotify app settings**, add `http://127.0.0.1:8888/callback` as a Redirect URI.

### 3. Authenticate with Spotify

On first run, the daemon will print an auth URL. Open it in your browser, authorize the app, then copy the full redirect URL (it will show a connection error — that's expected) and paste it back into the terminal.

Alternatively, use the helper script:

```bash
.venv/bin/python test_playlist.py
# Follow the printed instructions
```

## Running

### As a systemd service (recommended — survives reboots)

Service unit files are included in the repository. Install them once and both
the daemon and web UI will start automatically on boot.

```bash
# 1. Copy the unit files into systemd's user-level service directory
sudo cp concert-watcher.service     /etc/systemd/system/
sudo cp concert-watcher-web.service /etc/systemd/system/

# 2. Reload systemd so it sees the new units
sudo systemctl daemon-reload

# 3. Enable both services to start on boot
sudo systemctl enable concert-watcher
sudo systemctl enable concert-watcher-web

# 4. Start them now (without rebooting)
sudo systemctl start concert-watcher
sudo systemctl start concert-watcher-web
```

Check status and logs:

```bash
sudo systemctl status concert-watcher
sudo journalctl -u concert-watcher -f          # follow live logs
sudo journalctl -u concert-watcher-web -f      # follow web UI logs
```

Stop or restart:

```bash
sudo systemctl stop    concert-watcher
sudo systemctl restart concert-watcher
```

> **Note:** The unit files assume the project is installed at
> `/home/joe/concert-watcher` and runs as user `joe`. If you installed it
> elsewhere or under a different user, edit the `User=` and `WorkingDirectory=`
> lines in both `.service` files before copying them.

### Manual / foreground (development)

```bash
.venv/bin/python -m src.main
# or in the background (no reboot persistence):
nohup .venv/bin/python -m src.main &
```

### Web UI (manual)

```bash
.venv/bin/python -m src.web.app
```

Then open `http://localhost:7474` in your browser.

### Manual Ticketmaster refresh

```bash
.venv/bin/python _tm_search.py
```

### Tests

```bash
.venv/bin/python -m pytest tests/
```

## Scheduler intervals (configurable in `config.yaml`)

| Job | Default |
|-----|---------|
| Recently played | Every 60 min |
| Playlists | Every 6 hours |
| Concert search | Every 12 hours |

## Data

- `data/tracker.db` — SQLite database (gitignored)
- `data/events.json` — JSON export of upcoming concerts (gitignored)

## Noise filtering

Artists that produce false-positive Ticketmaster results (tribute bands, cover shows) can be suppressed in two ways:

1. **`skip_artists`** in `config.yaml` — skips the TM search entirely for that artist
2. **`filtered` flag** in the DB — events flagged `filtered=1` are hidden from the UI and `events.json` but preserved for reference
