from __future__ import annotations

import os
import sqlite3
from typing import Optional

SCHEMA_VERSION = 1

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS torrents (
  id INTEGER PRIMARY KEY,
  topic_url TEXT UNIQUE NOT NULL,
  title TEXT,
  discovered_at TEXT,
  last_seen_in_feed TEXT,
  magnet_url TEXT,
  torrent_url TEXT,
  infohash TEXT,
  size_bytes INTEGER,
  porla_torrent_id TEXT,
  porla_name TEXT,
  added_to_porla_at TEXT,
  last_stats_at TEXT,
  seeders INTEGER,
  leechers INTEGER,
  downloaded INTEGER,
  score REAL,
  status TEXT,
  last_error TEXT,
  topic_last_fetched_at TEXT,
  topic_etag TEXT,
  topic_last_modified TEXT
);

CREATE INDEX IF NOT EXISTS idx_torrents_porla_id ON torrents (porla_torrent_id);
CREATE INDEX IF NOT EXISTS idx_torrents_status ON torrents (status);

CREATE TABLE IF NOT EXISTS tracker_endpoints (
  id INTEGER PRIMARY KEY,
  torrent_id INTEGER NOT NULL,
  tracker_url TEXT NOT NULL,
  last_scrape_at TEXT,
  scrape_complete INTEGER,
  scrape_incomplete INTEGER,
  scrape_downloaded INTEGER,
  scrape_status TEXT,
  last_error TEXT,
  UNIQUE (torrent_id, tracker_url),
  FOREIGN KEY (torrent_id) REFERENCES torrents (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY,
  run_type TEXT NOT NULL,
  started_at TEXT,
  finished_at TEXT,
  ok INTEGER,
  summary TEXT
);

CREATE TABLE IF NOT EXISTS reconcile_actions (
  id INTEGER PRIMARY KEY,
  torrent_id INTEGER,
  action TEXT NOT NULL,
  reason TEXT,
  created_at TEXT,
  FOREIGN KEY (torrent_id) REFERENCES torrents (id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,
  value TEXT
);

CREATE TABLE IF NOT EXISTS http_cache (
  url TEXT PRIMARY KEY,
  etag TEXT,
  last_modified TEXT,
  last_fetched_at TEXT
);
"""


def connect(db_path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL)
    conn.execute(
        "INSERT OR IGNORE INTO meta (key, value) VALUES (?, ?)",
        ("schema_version", str(SCHEMA_VERSION)),
    )
    conn.commit()


def get_meta(conn: sqlite3.Connection, key: str) -> Optional[str]:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    if not row:
        return None
    return row["value"]


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    conn.commit()


def record_run(
    conn: sqlite3.Connection,
    run_type: str,
    started_at: str,
    finished_at: str,
    ok: bool,
    summary: str,
) -> None:
    conn.execute(
        "INSERT INTO runs (run_type, started_at, finished_at, ok, summary) VALUES (?, ?, ?, ?, ?)",
        (run_type, started_at, finished_at, 1 if ok else 0, summary),
    )
    conn.commit()


def record_action(
    conn: sqlite3.Connection,
    torrent_id: Optional[int],
    action: str,
    reason: str,
    created_at: str,
) -> None:
    conn.execute(
        "INSERT INTO reconcile_actions (torrent_id, action, reason, created_at) VALUES (?, ?, ?, ?)",
        (torrent_id, action, reason, created_at),
    )
    conn.commit()
