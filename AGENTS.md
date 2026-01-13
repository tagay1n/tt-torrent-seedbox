You are Codex. Build a production-quality “policy engine” for an Ubuntu 22.04 seedbox that uses Porla (installed bare-metal, not Docker) as the torrent client.

PROJECT GOAL
We want an automated archival seeding manager for a public Tatar-language tracker site (website powered by phpBB/Board3 Portal). The site exposes:
- https://SITE/feed.php (RSS/Atom) for incremental discovery of new torrent topics
- https://SITE/robots.txt and https://SITE/sitemap.xml exist (sitemap optional for initial backfill)

We will:
- Discover “new torrents” via feed.php every 30–60 minutes
- For each discovered item, capture metadata (title, topic URL, magnet or .torrent link, size, timestamps)
- Add it to Porla (tagged) so it can download + seed
- Obtain seed/leech/downloaded counts via Porla’s tracker scrape stats for that torrent (scrape_complete/scrape_incomplete/scrape_downloaded if Porla provides them)
- Maintain a SQLite catalog of torrents and their stats
- Periodically compute “vulnerability” and keep only top N (e.g., top 5000) within a disk cap (<= 1 TB). Rotate out others by removing from Porla and deleting data.
- Guardrails:
  - never delete torrents currently downloading
  - never delete torrents on a “pinned” list
- Observability:
  - integrate with Uptime Kuma by exposing HTTP endpoints (/healthz, /readyz) and clear logs
  - provide a rich local dashboard web UI to show system state and “vulnerable torrents” and tracker health; plan for future multi-tracker dashboards
- No Telegram posting yet.

TECH STACK REQUIREMENTS
- Ubuntu 22.04
- Porla is not installed and you need to create a make command running it as a systemd service (but you only need to control Porla through HTTP API)
- Our policy engine is a Python 3.10+ project
- Use SQLite (single file) for state
- Provide systemd services + systemd timers to run collectors/reconciler automatically
- Provide Makefile targets to manage lifecycle (install deps, init db, run locally, install/uninstall systemd units, view logs, status)
- No SSH requirements (operator runs commands locally)

HIGH-LEVEL ARCHITECTURE
Create a Python package with these components:

1) Config
- config.yaml with:
  - tracker base URL (SITE), feed URL
  - polite crawl parameters (user agent, rate limit)
  - allowed mode: allow_forums / allow_tags / allow_regex_title (all optional)
  - Porla API base URL + auth (token or basic, depending on Porla config)
  - disk cap: max_total_bytes (900 GB), max_torrents (50000)
  - Porla tag used for managed torrents (e.g. “tt-archive”)
  - pinned list file path (pinned.txt) and “never delete if pinned” bool
  - optional fallback: html_parse_enabled = false by default

1) Storage (SQLite)
- sqlite db file: data/state.db
- tables (at minimum):
  - torrents(
      id INTEGER PK,
      topic_url TEXT UNIQUE NOT NULL,
      title TEXT,
      discovered_at DATETIME,
      last_seen_in_feed DATETIME,
      magnet_url TEXT,
      torrent_url TEXT,
      infohash TEXT,
      size_bytes INTEGER,
      porla_torrent_id TEXT,
      porla_name TEXT,
      added_to_porla_at DATETIME,
      last_stats_at DATETIME,
      seeders INTEGER,
      leechers INTEGER,
      downloaded INTEGER,
      score REAL,
      status TEXT,           -- e.g. new/queued/downloading/seeding/stalled/removed
      last_error TEXT
    )
  - tracker_endpoints(
      id INTEGER PK,
      torrent_id FK -> torrents.id,
      tracker_url TEXT,
      last_scrape_at DATETIME,
      scrape_complete INTEGER,
      scrape_incomplete INTEGER,
      scrape_downloaded INTEGER,
      scrape_status TEXT,    -- ok/unsupported/error
      last_error TEXT
    )
  - runs(
      id INTEGER PK,
      run_type TEXT,         -- ingest/stats/reconcile
      started_at DATETIME,
      finished_at DATETIME,
      ok INTEGER,
      summary TEXT
    )

1) Ingestor
- fetch and parse feed.php (RSS/Atom) with feedparser
- store/refresh torrents in DB
- for each new topic_url:
  - fetch topic page ONLY if needed to extract magnet/torrent download link & size (polite: 1 req/sec; respect robots disallow list)
  - Extract:
    - magnet link (preferred)
    - or .torrent attachment link
    - and size if present
- If both magnet and .torrent are absent, mark last_error and skip
- Do NOT crawl deep lists; only the topic pages referenced by the feed
- Add robust HTTP caching (ETag/If-Modified-Since) when possible, and local caching so the same topic isn’t refetched too often

1) Porla client wrapper
- Write a small module porla_client.py that:
  - checks Porla health endpoint (or simple GET ping)
  - adds torrent by magnet URL or .torrent URL (if Porla supports URL add)
  - tags torrent with managed tag
  - lists torrents filtered by tag (pagination safe)
  - fetches per-torrent tracker list and scrape stats (seed/leech/downloaded)
  - gets torrent state to avoid deleting active downloads
  - removes torrent and optionally deletes data
- Handle auth cleanly via config.
- Implement retries/backoff for transient errors.

1) Stats updater
- For torrents already in Porla:
  - poll Porla for torrent state + scrape stats
  - update DB columns seeders/leechers/downloaded, plus tracker_endpoints rows
  - treat scrape fields unavailable as “unsupported” (e.g., -1) and keep last known stats

1) Scoring + selection
Default selection criteria:
- We prioritize vulnerability as:
  seeders asc, leechers desc, age desc, size asc
Implement as either:
- a deterministic sort key (preferred for transparency) OR a weighted score (optional)
Add a small size penalty to favor fitting more torrents under disk cap.

We compute a keep-set:
- Target: keep up to max_torrents (50000) AND keep total size <= 900 GB
- Only include torrents with known size_bytes; unknown size goes to a separate “unknown” bucket and is excluded from keep-set by default
- Pinned torrents are always kept (if they exist in Porla); if pinned exceeds disk cap, log a warning but don’t delete pinned automatically

7) Reconciler (Porla sync)
- Ensure all keep-set torrents are present in Porla and tagged
- Remove torrents that are managed (tagged) but not in keep-set:
  - Guardrail: do not delete torrents currently downloading
  - If allow_delete_data=true, remove from Porla with delete data to free disk
- Record actions in runs table

8) Observability + Dashboard
A) HTTP health server (FastAPI preferred)
- Expose:
  - GET /healthz  -> returns 200 if process is up
  - GET /readyz   -> 200 if DB reachable and Porla ping ok
  - GET /metrics  -> Prometheus text format basic metrics (optional but nice)
Metrics to include:
- last_ingest_ok, last_stats_ok, last_reconcile_ok (unix timestamps)
- db_torrents_total
- porla_managed_total
- vulnerable_critical_count (e.g. seeders <= 1 and leechers > 0)
- disk_used_bytes / disk_free_bytes (use OS statvfs)
- errors_last_24h

B) Rich dashboard web UI (served by the same FastAPI app)
- Use server-rendered HTML (Jinja2) + a little JS/HTMX for table refresh
- Pages:
  - “Overview”:
     - last run times, Porla status, disk usage, counts by status
  - “Vulnerable”:
     - table: title, size, seeders, leechers, age, score, topic link
     - filters: critical (seeders<=1), actionable (seeders>=1), pinned
  - “Trackers”:
     - show tracker endpoints and scrape support/health from tracker_endpoints table
  - “Actions log”:
     - last N reconcile actions (added/removed/skipped + reason)
- Auto-refresh every ~60s (configurable).
- This dashboard should be local-first but designed so it can later be hosted as a separate web page.

SCHEDULING
Use systemd timers (NOT cron) for three tasks:
- ingest.service + ingest.timer every 30–60 minutes (choose 45 min default)
- stats.service + stats.timer every 30–60 minutes (can run after ingest; default 60 min)
- reconcile.service + reconcile.timer daily (default 03:30 local)
Additionally, run dashboard.service continuously (FastAPI server).

MAKEFILE REQUIREMENTS
Provide a Makefile with targets:
- make venv          (create venv)
- make deps          (install deps)
- make initdb        (create schema/migrate)
- make run-ingest
- make run-stats
- make run-reconcile
- make run-dashboard (local dev)
- make install-systemd   (copy unit files to /etc/systemd/system, daemon-reload, enable timers, enable dashboard)
- make uninstall-systemd (disable + remove units)
- make status        (systemctl status for our units)
- make logs          (journalctl -u <unit> -n 200 --no-pager)
- make fmt/lint/test (use ruff + pytest)
All commands should work when run locally on the laptop.

SYSTEMD UNIT FILES
Create unit files under deploy/systemd/:
- ttseed-ingest.service + ttseed-ingest.timer
- ttseed-stats.service + ttseed-stats.timer
- ttseed-reconcile.service + ttseed-reconcile.timer
- ttseed-dashboard.service
Use ExecStart calling the venv python with module entrypoints.
Set:
- Restart=on-failure for dashboard
- Hardening: PrivateTmp=true, NoNewPrivileges=true (reasonable defaults)
- WorkingDirectory=/opt/ttseed (assume install path)
The Makefile install-systemd should install to /opt/ttseed and set permissions.

ROBUSTNESS & POLITENESS
- Respect robots.txt disallow paths (implement a small robots parser or use urllib.robotparser)
- Rate limit requests to the tracker website (1 request/sec default)
- Use a persistent HTTP session with timeouts and retries
- Cache topic page fetches and avoid repeated scraping
- Store last_error but don’t crash the whole service on one bad page

DATA EXTRACTION
- Feed entries provide title + link to topic URL.
- Topic page must yield magnet or .torrent URL (implementation can be heuristic; search for “magnet:” links or attachment download links).
- If size appears on page, parse it (support KB/MB/GB/TB).
- Do not implement heavy scraping of lists or search pages; only pages referenced by the feed.

PORLA INTEGRATION
- Assume Porla exposes an HTTP API. Implement an adapter that can be configured for endpoint paths and auth.
- If Porla returns scrape stats at the tracker level, map them to seeders/leechers/downloaded and store to DB.
- If scrape stats are unavailable, leave them NULL and continue.

DELIVERABLES
- A complete repository layout:
  - pyproject.toml
  - src/ttseed/ (modules)
  - data/ (db path)
  - deploy/systemd/
  - config.example.yaml
  - README.md with setup steps for Ubuntu 22.04 and Porla base configuration
- The code must run end-to-end (even with SITE as a placeholder), and have clear “TODO: configure selectors” only where unavoidable.
- Include minimal unit tests for scoring and DB operations.

Start by generating:
1) repo structure
2) config schema
3) DB schema + migration/init
4) Porla client adapter (with mocked tests)
5) ingest + stats + reconcile commands
6) FastAPI dashboard + health endpoints
7) Makefile + systemd units
8) README

Make reasonable defaults and document them but feel free to ask questions
