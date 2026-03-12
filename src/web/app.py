"""
Concert Watcher web UI.

Run:  .venv/bin/python -m src.web.app
Then: http://spacebot:7474
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from flask import Flask, jsonify, render_template_string

app = Flask(__name__)

_PROJECT_ROOT = Path(__file__).parent.parent.parent
DB_PATH = _PROJECT_ROOT / "data" / "tracker.db"

# ---------------------------------------------------------------------------
# HTML / CSS / JS  (single-page, no external dependencies)
# ---------------------------------------------------------------------------

_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Concert Watcher</title>
  <style>
    /* ── Dracula palette ─────────────────────────────────────────────── */
    :root {
      --bg:           #282a36;
      --bg-dark:      #1e1f29;
      --line:         #44475a;
      --fg:           #f8f8f2;
      --comment:      #6272a4;
      --cyan:         #8be9fd;
      --green:        #50fa7b;
      --orange:       #ffb86c;
      --pink:         #ff79c6;
      --purple:       #bd93f9;
      --red:          #ff5555;
      --yellow:       #f1fa8c;
    }

    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

    body {
      background: var(--bg);
      color: var(--fg);
      font-family: 'Courier New', Courier, monospace;
      min-height: 100vh;
    }

    /* ── Header ─────────────────────────────────────────────────────── */
    header {
      background: var(--bg-dark);
      border-bottom: 2px solid var(--purple);
      padding: 14px 24px;
      display: flex;
      align-items: center;
      gap: 12px;
    }

    header h1 {
      color: var(--pink);
      font-size: 1.35rem;
      letter-spacing: 3px;
      text-transform: uppercase;
    }

    .header-stats {
      margin-left: auto;
      display: flex;
      gap: 28px;
      font-size: 0.82rem;
      color: var(--comment);
    }

    .header-stats span b {
      color: var(--cyan);
      font-weight: bold;
    }

    /* ── Controls bar ────────────────────────────────────────────────── */
    .controls {
      background: var(--bg-dark);
      border-bottom: 1px solid var(--line);
      padding: 12px 24px;
      display: flex;
      align-items: center;
      gap: 20px;
      flex-wrap: wrap;
    }

    .search-wrap {
      position: relative;
    }

    .search-wrap::before {
      content: '⌕';
      position: absolute;
      left: 10px;
      top: 50%;
      transform: translateY(-50%);
      color: var(--comment);
      font-size: 1rem;
      pointer-events: none;
    }

    #search {
      background: var(--bg);
      border: 1px solid var(--line);
      border-radius: 4px;
      color: var(--fg);
      padding: 7px 12px 7px 30px;
      font-family: inherit;
      font-size: 0.88rem;
      width: 300px;
      outline: none;
      transition: border-color 0.15s;
    }

    #search:focus { border-color: var(--purple); }
    #search::placeholder { color: var(--comment); }

    /* toggle switch */
    .toggle-wrap {
      display: flex;
      align-items: center;
      gap: 9px;
      cursor: pointer;
      user-select: none;
      font-size: 0.88rem;
      color: var(--comment);
    }

    .toggle-wrap input { display: none; }

    .toggle-track {
      width: 38px;
      height: 22px;
      background: var(--line);
      border-radius: 11px;
      position: relative;
      transition: background 0.2s;
      flex-shrink: 0;
    }

    .toggle-track::after {
      content: '';
      position: absolute;
      width: 16px;
      height: 16px;
      background: var(--fg);
      border-radius: 50%;
      top: 3px;
      left: 3px;
      transition: left 0.2s;
    }

    .toggle-wrap input:checked + .toggle-track { background: var(--purple); }
    .toggle-wrap input:checked + .toggle-track::after { left: 19px; }

    .toggle-wrap:hover .toggle-track { border: 1px solid var(--purple); }

    .result-count {
      margin-left: auto;
      font-size: 0.82rem;
      color: var(--comment);
    }

    /* ── Table ───────────────────────────────────────────────────────── */
    .table-wrap {
      overflow-x: auto;
      padding: 16px 24px 32px;
    }

    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 0.87rem;
    }

    thead th {
      background: var(--bg-dark);
      color: var(--pink);
      padding: 9px 13px;
      text-align: left;
      font-size: 0.75rem;
      letter-spacing: 1.5px;
      text-transform: uppercase;
      border-bottom: 2px solid var(--purple);
      white-space: nowrap;
      user-select: none;
    }

    thead th[data-col] {
      cursor: pointer;
    }

    thead th[data-col]:hover { color: var(--cyan); }

    thead th.asc::after  { content: ' \25B2'; color: var(--purple); }
    thead th.desc::after { content: ' \25BC'; color: var(--purple); }

    tbody tr {
      border-bottom: 1px solid var(--line);
      transition: background 0.1s;
    }

    tbody tr:hover { background: var(--line); }

    tbody tr.tribute {
      background: rgba(255, 85, 85, 0.05);
      border-left: 3px solid var(--red);
    }

    td { padding: 11px 13px; vertical-align: middle; }

    td.artist { color: var(--green);  font-weight: bold; }
    td.added  { color: var(--comment); white-space: nowrap; }
    td.event  { color: var(--fg); }
    td.venue  { color: var(--fg); }
    td.city   { color: var(--comment); white-space: nowrap; }
    td.dist   { color: var(--orange); text-align: right; white-space: nowrap; }
    td.price  { color: var(--cyan); white-space: nowrap; }

    td.artist.tribute-artist { color: var(--red); }

    .tribute-tag {
      color: var(--red);
      font-size: 0.78rem;
      font-weight: normal;
      font-style: italic;
      margin-left: 6px;
      opacity: 0.85;
    }

    td.ticket a {
      color: var(--purple);
      text-decoration: none;
      border: 1px solid var(--purple);
      border-radius: 3px;
      padding: 3px 8px;
      font-size: 0.75rem;
      letter-spacing: 0.5px;
      white-space: nowrap;
      transition: background 0.15s, color 0.15s;
    }

    td.ticket a:hover {
      background: var(--purple);
      color: var(--bg);
    }

    /* ── Empty / loading states ──────────────────────────────────────── */
    .state-msg {
      text-align: center;
      padding: 56px 24px;
      color: var(--comment);
      font-size: 0.95rem;
      letter-spacing: 1px;
    }

    .state-msg.loading { color: var(--purple); }

    /* ── Mobile: card layout ─────────────────────────────────────────── */
    @media (max-width: 700px) {
      header {
        flex-wrap: wrap;
        padding: 12px 16px;
        gap: 8px;
      }

      header h1 {
        font-size: 1.05rem;
        letter-spacing: 2px;
      }

      .header-stats {
        margin-left: 0;
        width: 100%;
        flex-wrap: wrap;
        gap: 10px 20px;
        font-size: 0.8rem;
      }

      .controls {
        padding: 10px 16px;
        gap: 10px;
      }

      .search-wrap { width: 100%; }

      #search { width: 100%; }

      .result-count { margin-left: 0; }

      .table-wrap { padding: 12px 12px 32px; }

      /* Convert table to stacked cards */
      table, tbody, tr, td { display: block; }
      thead { display: none; }

      tr {
        border: 1px solid var(--line);
        border-radius: 6px;
        padding: 10px 14px;
        margin-bottom: 12px;
        background: var(--bg-dark);
      }

      tr.tribute {
        border-left: 3px solid var(--red);
        background: rgba(255, 85, 85, 0.05);
      }

      tr:hover { background: var(--line); }

      td {
        display: flex;
        align-items: baseline;
        padding: 4px 0;
        border: none;
      }

      td::before {
        content: attr(data-label);
        color: var(--comment);
        font-size: 0.7rem;
        letter-spacing: 1px;
        text-transform: uppercase;
        min-width: 62px;
        flex-shrink: 0;
        margin-right: 10px;
      }

      td.artist {
        font-size: 1rem;
        padding-bottom: 8px;
        border-bottom: 1px solid var(--line);
        margin-bottom: 4px;
      }

      td.artist::before { display: none; }

      td.dist  { text-align: left; }
      td.price { text-align: left; }
    }
  </style>
</head>
<body>

<header>
  <h1>Concert Watcher</h1>
  <div class="header-stats" id="hstats"></div>
</header>

<div class="controls">
  <div class="search-wrap">
    <input type="text" id="search" placeholder="Filter by artist, venue, or city…" autocomplete="off">
  </div>

  <label class="toggle-wrap" title="Show tribute bands and false-match events">
    <input type="checkbox" id="tog-tribute">
    <span class="toggle-track"></span>
    <span id="tog-label">Show tributes / false matches</span>
  </label>

  <span class="result-count" id="rcount"></span>
</div>

<div class="table-wrap">
  <div class="state-msg loading" id="msg">Loading…</div>
  <table id="tbl" hidden>
    <thead>
      <tr>
        <th data-col="date">Date</th>
        <th data-col="added">Added</th>
        <th data-col="artist">Artist</th>
        <th data-col="event_name">Event</th>
        <th data-col="venue">Venue</th>
        <th data-col="city">City</th>
        <th data-col="distance_miles">Miles</th>
        <th data-col="price_min">Price</th>
        <th>Tickets</th>
      </tr>
    </thead>
    <tbody id="tbody"></tbody>
  </table>
</div>

<script>
  'use strict';

  let ALL = [];
  let sortCol = 'date';
  let sortDir = 1;   // 1 = asc, -1 = desc

  // ── fetch ────────────────────────────────────────────────────────────
  async function load() {
    try {
      const r = await fetch('/api/concerts');
      const d = await r.json();
      ALL = d.concerts;
      renderStats();
      document.getElementById('msg').hidden = true;
      document.getElementById('tbl').hidden = false;
      render();
    } catch (e) {
      document.getElementById('msg').textContent = 'Failed to load data.';
      document.getElementById('msg').classList.remove('loading');
    }
  }

  // ── header stats ─────────────────────────────────────────────────────
  function renderStats() {
    const real = ALL.filter(c => !c.filtered);
    const artists = new Set(real.map(c => c.artist)).size;
    const tributes = ALL.filter(c => c.filtered).length;
    const el = document.getElementById('hstats');
    el.innerHTML =
      `<span>Artists: <b>${artists}</b></span>` +
      `<span>Concerts: <b>${real.length}</b></span>` +
      (tributes ? `<span>Flagged: <b style="color:var(--red)">${tributes}</b></span>` : '') +
      `<span>Updated: <b>${new Date().toLocaleDateString()}</b></span>`;

    // Toggle label: show count, dim if zero
    const togLabel = document.getElementById('tog-label');
    if (tributes === 0) {
      togLabel.textContent = 'Show tributes / false matches';
      togLabel.style.opacity = '0.4';
      togLabel.title = 'No flagged entries in database yet — they will appear after the next concert search run.';
    } else {
      togLabel.textContent = `Show tributes / false matches (${tributes})`;
      togLabel.style.opacity = '';
      togLabel.title = '';
    }
  }

  // ── sort key ─────────────────────────────────────────────────────────
  function key(c, col) {
    switch (col) {
      case 'date':           return c.date;
      case 'added':          return c.added;
      case 'artist':         return c.artist.toLowerCase();
      case 'event_name':     return c.event_name.toLowerCase();
      case 'venue':          return c.venue.toLowerCase();
      case 'city':           return c.city.toLowerCase();
      case 'distance_miles': return c.distance_miles;
      case 'price_min':      return c.price_min ?? Infinity;
      default:               return '';
    }
  }

  // ── main render ──────────────────────────────────────────────────────
  function render() {
    const q = document.getElementById('search').value.trim().toLowerCase();
    const showTrib = document.getElementById('tog-tribute').checked;

    let rows = ALL.filter(c => {
      if (c.filtered && !showTrib) return false;
      if (!q) return true;
      return c.artist.toLowerCase().includes(q) ||
             c.venue.toLowerCase().includes(q) ||
             c.city.toLowerCase().includes(q) ||
             c.event_name.toLowerCase().includes(q);
    });

    rows.sort((a, b) => {
      const av = key(a, sortCol), bv = key(b, sortCol);
      if (av < bv) return -sortDir;
      if (av > bv) return  sortDir;
      return 0;
    });

    // column sort indicators
    document.querySelectorAll('thead th[data-col]').forEach(th => {
      th.classList.toggle('asc',  th.dataset.col === sortCol && sortDir ===  1);
      th.classList.toggle('desc', th.dataset.col === sortCol && sortDir === -1);
    });

    const real   = ALL.filter(c => !c.filtered).length;
    const tribs  = ALL.filter(c =>  c.filtered).length;
    const rcEl   = document.getElementById('rcount');
    rcEl.textContent = `Showing ${rows.length} of ${real}` +
                       (tribs ? ` (+${tribs} flagged)` : '');

    const tbody = document.getElementById('tbody');
    if (!rows.length) {
      tbody.innerHTML =
        `<tr><td colspan="9" class="state-msg">No concerts match your filters.</td></tr>`;
      return;
    }

    tbody.innerHTML = rows.map(c => {
      const priceStr = c.price_min != null
        ? `$${Math.round(c.price_min)}&ndash;$${Math.round(c.price_max ?? c.price_min)}`
        : `<span style="color:var(--comment)">—</span>`;
      const distStr = c.distance_miles > 0
        ? `${Math.round(c.distance_miles)} mi`
        : `<span style="color:var(--comment)">—</span>`;
      const ticketStr = c.ticket_url
        ? `<a href="${esc(c.ticket_url)}" target="_blank" rel="noopener noreferrer">BUY</a>`
        : `<span style="color:var(--comment)">—</span>`;
      const tributeTag = c.filtered ? `<span class="tribute-tag">(Tribute)</span>` : '';

      return `<tr class="${c.filtered ? 'tribute' : ''}">
        <td class="date"    data-label="Date">${esc(c.date)}</td>
        <td class="added"   data-label="Added">${esc(c.added)}</td>
        <td class="artist${c.filtered ? ' tribute-artist' : ''}">${esc(c.artist)}${tributeTag}</td>
        <td class="event"   data-label="Event">${esc(c.event_name)}</td>
        <td class="venue"   data-label="Venue">${esc(c.venue)}</td>
        <td class="city"    data-label="City">${esc(c.city)}</td>
        <td class="dist"    data-label="Miles">${distStr}</td>
        <td class="price"   data-label="Price">${priceStr}</td>
        <td class="ticket"  data-label="Tickets">${ticketStr}</td>
      </tr>`;
    }).join('');
  }

  // ── helpers ──────────────────────────────────────────────────────────
  function esc(s) {
    return String(s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  // ── wire events ──────────────────────────────────────────────────────
  document.querySelectorAll('thead th[data-col]').forEach(th => {
    th.addEventListener('click', () => {
      if (sortCol === th.dataset.col) {
        sortDir *= -1;
      } else {
        sortCol = th.dataset.col;
        sortDir = 1;
      }
      render();
    });
  });

  document.getElementById('search').addEventListener('input', render);
  document.getElementById('tog-tribute').addEventListener('change', render);

  load();
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index() -> str:
    return render_template_string(_HTML)


@app.route("/api/concerts")
def api_concerts():
    """Return all upcoming concerts (real + flagged) from the DB."""
    if not DB_PATH.exists():
        return jsonify({"concerts": [], "error": "Database not found"})

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT id, artist_name, event_name, venue_name, venue_city,
                   event_date, distance_miles, ticket_url,
                   price_min, price_max, currency, filtered,
                   first_discovered_at
            FROM concerts
            WHERE event_date >= date('now')
            ORDER BY event_date, artist_name
            """
        ).fetchall()
    finally:
        conn.close()

    concerts = [
        {
            "id":             r["id"],
            "artist":         r["artist_name"],
            "event_name":     r["event_name"],
            "venue":          r["venue_name"],
            "city":           r["venue_city"],
            "date":           r["event_date"][:10],
            "added":          r["first_discovered_at"][:10],
            "distance_miles": r["distance_miles"],
            "ticket_url":     r["ticket_url"],
            "price_min":      r["price_min"],
            "price_max":      r["price_max"],
            "currency":       r["currency"],
            "filtered":       bool(r["filtered"]),
        }
        for r in rows
    ]
    return jsonify({"concerts": concerts})


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=7474, debug=False)
