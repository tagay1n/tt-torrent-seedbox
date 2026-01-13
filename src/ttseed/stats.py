from __future__ import annotations

from ttseed.config import load_config
from ttseed.db import connect, init_db, record_run, set_meta
from ttseed.http_client import build_session
from ttseed.logging_setup import setup_logging
from ttseed.porla_client import PorlaClient
from ttseed.util import iso_now


def run(config_path: str) -> None:
    logger = setup_logging()
    cfg = load_config(config_path)
    session = build_session(cfg.porla.retry_count)
    porla = PorlaClient(cfg.porla, session)

    conn = connect(cfg.storage.db_path)
    init_db(conn)

    started_at = iso_now()
    ok = True
    updated = 0

    logger.info("stats run started")
    rows = conn.execute(
        "SELECT id, porla_torrent_id FROM torrents WHERE porla_torrent_id IS NOT NULL"
    ).fetchall()

    for row in rows:
        torrent_id = row["porla_torrent_id"]
        torrent = porla.get_torrent(torrent_id)
        if not torrent:
            conn.execute(
                "UPDATE torrents SET status = ?, last_error = ? WHERE id = ?",
                ("missing", "porla not found", row["id"]),
            )
            conn.commit()
            ok = False
            continue
        trackers = porla.get_trackers(torrent_id)

        max_complete = None
        max_incomplete = None
        max_downloaded = None
        for tracker in trackers:
            conn.execute(
                "INSERT INTO tracker_endpoints (torrent_id, tracker_url, last_scrape_at, scrape_complete, scrape_incomplete, scrape_downloaded, scrape_status, last_error) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(torrent_id, tracker_url) DO UPDATE SET last_scrape_at = excluded.last_scrape_at, scrape_complete = excluded.scrape_complete, scrape_incomplete = excluded.scrape_incomplete, scrape_downloaded = excluded.scrape_downloaded, scrape_status = excluded.scrape_status, last_error = excluded.last_error",
                (
                    row["id"],
                    tracker.tracker_url,
                    iso_now(),
                    tracker.scrape_complete,
                    tracker.scrape_incomplete,
                    tracker.scrape_downloaded,
                    tracker.scrape_status,
                    None,
                ),
            )
            if tracker.scrape_complete is not None:
                max_complete = max(max_complete or 0, tracker.scrape_complete)
            if tracker.scrape_incomplete is not None:
                max_incomplete = max(max_incomplete or 0, tracker.scrape_incomplete)
            if tracker.scrape_downloaded is not None:
                max_downloaded = max(max_downloaded or 0, tracker.scrape_downloaded)

        conn.execute(
            "UPDATE torrents SET porla_name = ?, status = ?, infohash = ?, size_bytes = COALESCE(size_bytes, ?), seeders = ?, leechers = ?, downloaded = ?, last_stats_at = ?, last_error = NULL WHERE id = ?",
            (
                torrent.name,
                torrent.state,
                torrent.infohash,
                torrent.size_bytes,
                max_complete,
                max_incomplete,
                max_downloaded,
                iso_now(),
                row["id"],
            ),
        )
        conn.commit()
        updated += 1

    set_meta(conn, "last_stats_at", iso_now())
    summary = f"updated={updated}"
    logger.info("stats complete %s", summary)
    record_run(conn, "stats", started_at, iso_now(), ok, summary)
