# ttseed

Minimal discovery + Porla ingest for a phpBB tracker.

## What it does
- Logs in to the tracker and crawls categories/topics to find .torrent links and stats.
- Stores torrents in SQLite.
- Pushes new torrents to Porla via JSON-RPC.
- `feed` command parses `feed.php` (currently for debugging).

## Requirements
- Ubuntu 22.04
- Python 3.10+
- Porla running and reachable via HTTP

## Quick start (local)
```bash
cp "config.example copy.yaml" config.yaml
make venv
make deps
make initdb
make discover
make ingest-porla
```

CLI help:
```bash
python src/cli.py --help
```

## Configuration
Edit `config.yaml`. Minimal keys used:

tracker:
- `base_url`
- `feed_url` (only used by `feed` command)
- `login_url`
- `login_username`
- `login_password`
- `login_cookie_prefix`

porla:
- `base_url`
- `token`
- `jsonrpc_url`
- `add_save_path`
- `retry_count`

storage:
- `db_path`

Login is required; `discover` will fail if credentials are missing.

## Discovery notes
- `discover` crawls categories from `/viewforum.php?f=49` and follows pagination.
- If your tracker uses a different forum id, change the default in `src/discover.py`.

## Porla API notes
JSON-RPC methods used:
- `torrents.add` (base64 .torrent file)

Porla setup guide: `deploy/porla-setup.md`.

## Database
SQLite DB lives at `data/state.db`. Main table: `torrents`.

## Makefile targets
- `make venv`
- `make deps`
- `make initdb`
- `make discover`
- `make feed`
- `make ingest-porla`
- `make fmt`
- `make lint`
