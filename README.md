# ttseed

Production-quality policy engine for archival seeding with Porla on Ubuntu 22.04.

## What it does
- Polls `feed.php` for new torrents and captures metadata.
- Fetches topic pages (polite, cached, robots-aware) when needed to find magnet or `.torrent` links.
- Adds torrents to Porla with a managed tag.
- Scrapes tracker stats via Porla and stores them in SQLite.
- Computes vulnerability and reconciles against disk and count caps.
- Exposes health endpoints and a local dashboard.

## Requirements
- Ubuntu 22.04
- Python 3.10+
- Porla running on the host and reachable via HTTP API

## Quick start (local)
```bash
cp config.example.yaml config.yaml
make venv
make deps
make initdb
make run-ingest
make run-stats
make run-reconcile
make run-dashboard
```

Dashboard: `http://127.0.0.1:8080`

Health endpoints:
- `/healthz`
- `/readyz`
- `/metrics`

## Configuration
Edit `config.yaml`. Key settings:

- `tracker.base_url` / `tracker.feed_url`
- `tracker.user_agent`, `tracker.rate_limit_per_sec`
- `tracker.sitemap_url`, `tracker.sitemap_backfill_enabled`, `tracker.sitemap_backfill_force`, `tracker.sitemap_backfill_limit`
- `tracker.sitemap_topic_regex` (regex filter for topic URLs)
- `tracker.allow_forums`, `tracker.allow_tags`, `tracker.allow_regex_title`
- `tracker.html_parse_enabled` (default false)
- `tracker.login_enabled`, `tracker.login_url`, `tracker.login_username`, `tracker.login_password`
- `porla.base_url`, `porla.token`, `porla.managed_tag`
- `porla.jsonrpc_url`
- `porla.add_preset`, `porla.add_save_path`, `porla.add_params` (JSON-RPC add options)
- `policy.max_total_bytes`, `policy.max_torrents`
- `policy.allow_delete_data`, `policy.pinned_list_path`
- `storage.db_path`

Pinned torrents live in `pinned.txt` by default. Accepts topic URLs, infohashes, or Porla IDs (one per line).

Tip: if the tracker’s `robots.txt` specifies `Crawl-delay`, ttseed will honor it by slowing requests below `rate_limit_per_sec`.

## Authenticated topic fetch (login)
If topic pages hide magnet/torrent links behind login, enable tracker login:
```yaml
tracker:
  login_enabled: true
  login_url: "https://SITE/ucp.php?mode=login"
  login_username: "YOUR_USER"
  login_password: "YOUR_PASS"
  login_cookie_prefix: "phpbb"
  login_extra:
    autologin: "on"
```
ttseed will fetch the login page, submit the form, and keep cookies in the same session for topic fetches.

## Sitemap backfill (initial ingest)
Enable once to seed the catalog from `sitemap.xml`:
```yaml
tracker:
  sitemap_backfill_enabled: true
  # Optional: use a local copy instead of fetching https://SITE/sitemap.xml
  # sitemap_url: "sitemap.xml"
  sitemap_topic_regex:
    - "^https?://[^/]+/viewtopic\\.php\\?(?:f=\\d+&t=\\d+|t=\\d+)$"
  sitemap_backfill_limit: 0  # 0 = no limit
```
After a successful run, the backfill is marked complete in the DB. To rerun, set
`tracker.sitemap_backfill_force: true` or delete the meta key `sitemap_backfill_done`.

## Porla API notes
ttseed calls JSON-RPC methods:
- `sys.versions` (health)
- `torrents.add` (magnet or torrent file)
- `torrents.list`
- `torrents.trackers.list`
- `torrents.remove`

If `torrents.add` requires a preset or save path, set `porla.add_preset` or
`porla.add_save_path` in `config.yaml`.
If tags are not supported by JSON-RPC, set `porla.tag_mode: "db"` to avoid touching non-managed torrents.

## Systemd install
```bash
make install-systemd
```
This copies the repo to `/opt/ttseed`, creates a venv, installs deps, and installs/enables the timers and dashboard service.

## Porla systemd unit
A starter unit file lives at `deploy/systemd/porla.service` (expects `/usr/local/bin/porla`). Adjust the ExecStart and environment file as needed, then run:

```bash
make install-porla-systemd
```

To remove:
```bash
make uninstall-porla-systemd
```

To uninstall ttseed services:
```bash
make uninstall-systemd
```

Check status and logs:
```bash
make status
make logs
make logs UNIT=ttseed-ingest.service
```

## Database
SQLite DB (via SQLAlchemy ORM) lives at `data/state.db` by default. Tables:
- `torrents`
- `tracker_endpoints`
- `runs`
- `reconcile_actions`

## Testing
```bash
make test
```

## Notes
- Unknown torrent sizes are excluded from the keep-set by default.
- Pinned torrents are always kept, even if they exceed caps.
- The reconciler never deletes torrents currently downloading.
