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
- `tracker.allow_forums`, `tracker.allow_tags`, `tracker.allow_regex_title`
- `tracker.html_parse_enabled` (default false)
- `porla.base_url`, `porla.auth`, `porla.managed_tag`
- `porla.endpoints` (override if Porla API differs)
- `policy.max_total_bytes`, `policy.max_torrents`
- `policy.allow_delete_data`, `policy.pinned_list_path`
- `storage.db_path`

Pinned torrents live in `pinned.txt` by default. Accepts topic URLs, infohashes, or Porla IDs (one per line).

## Porla API notes
The client expects endpoints similar to:
- `GET /api/v1/health`
- `GET /api/v1/torrents?tag=TAG&page=1&pageSize=200`
- `POST /api/v1/torrents` with `magnetUrl` or `torrentUrl`
- `GET /api/v1/torrents/{id}`
- `GET /api/v1/torrents/{id}/trackers`
- `DELETE /api/v1/torrents/{id}?deleteData=true`

If your Porla API differs, adjust `porla.endpoints` and field names in `src/ttseed/porla_client.py`.

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
SQLite DB lives at `data/state.db` by default. Tables:
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
