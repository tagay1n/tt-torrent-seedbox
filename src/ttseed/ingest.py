from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Dict, Optional
from urllib.parse import urljoin

import feedparser

from ttseed.config import Config, load_config
from ttseed.db import connect, init_db, set_meta
from ttseed.http_client import RateLimiter, RobotsChecker, build_session
from ttseed.logging_setup import setup_logging
from ttseed.porla_client import PorlaClient
from ttseed.util import any_regex_match, extract_infohash, iso_now, parse_forum_id, parse_size

MAGNET_HREF_RE = re.compile(r"magnet:\?[^\"'\s]+", re.IGNORECASE)
HREF_RE = re.compile(r"href=[\"']([^\"']+)[\"']", re.IGNORECASE)


def _entry_tags(entry: Dict) -> list[str]:
    tags = []
    for tag in entry.get("tags", []) or []:
        term = tag.get("term") if isinstance(tag, dict) else None
        if term:
            tags.append(str(term))
    return tags


def _allowed_by_filters(cfg: Config, title: str, topic_url: str, entry: Dict) -> bool:
    tracker = cfg.tracker
    if tracker.allow_forums:
        forum_id = parse_forum_id(topic_url)
        if forum_id not in tracker.allow_forums:
            return False
    if tracker.allow_tags:
        tags = _entry_tags(entry)
        if not any(tag in tracker.allow_tags for tag in tags):
            return False
    if tracker.allow_regex_title:
        if not any_regex_match(tracker.allow_regex_title, title):
            return False
    return True


def _extract_links_from_entry(entry: Dict) -> tuple[Optional[str], Optional[str]]:
    magnet_url = None
    torrent_url = None
    for link in entry.get("links", []) or []:
        href = link.get("href") if isinstance(link, dict) else None
        if not href:
            continue
        if href.startswith("magnet:"):
            magnet_url = href
        if href.endswith(".torrent"):
            torrent_url = href
    summary = entry.get("summary", "") or ""
    if not magnet_url:
        match = MAGNET_HREF_RE.search(summary)
        if match:
            magnet_url = match.group(0)
    return magnet_url, torrent_url


def _extract_from_html(base_url: str, html: str) -> tuple[Optional[str], Optional[str], Optional[int]]:
    magnet_url = None
    torrent_url = None
    size_bytes = parse_size(html)
    match = MAGNET_HREF_RE.search(html)
    if match:
        magnet_url = match.group(0)
    for href in HREF_RE.findall(html):
        if href.startswith("magnet:"):
            magnet_url = href
            continue
        if ".torrent" in href:
            torrent_url = urljoin(base_url, href)
    return magnet_url, torrent_url, size_bytes


def run(config_path: str) -> None:
    logger = setup_logging()
    cfg = load_config(config_path)
    session = build_session(cfg.porla.retry_count)
    session.headers.update({"User-Agent": cfg.tracker.user_agent})

    conn = connect(cfg.storage.db_path)
    init_db(conn)

    limiter = RateLimiter(min_interval=1.0 / max(cfg.tracker.rate_limit_per_sec, 0.1))
    robots = RobotsChecker(cfg.tracker.base_url, session, cfg.tracker.user_agent)
    porla = PorlaClient(cfg.porla, session)

    started_at = iso_now()
    new_count = 0
    skipped_count = 0

    feed_headers = {}
    feed_cache = conn.execute(
        "SELECT etag, last_modified FROM http_cache WHERE url = ?",
        (cfg.tracker.feed_url,),
    ).fetchone()
    if feed_cache:
        if feed_cache["etag"]:
            feed_headers["If-None-Match"] = feed_cache["etag"]
        if feed_cache["last_modified"]:
            feed_headers["If-Modified-Since"] = feed_cache["last_modified"]

    limiter.wait()
    resp = session.get(cfg.tracker.feed_url, headers=feed_headers, timeout=20)
    if resp.status_code == 304:
        logger.info("feed not modified")
        set_meta(conn, "last_ingest_at", iso_now())
        conn.execute(
            "INSERT INTO runs (run_type, started_at, finished_at, ok, summary) VALUES (?, ?, ?, ?, ?)",
            ("ingest", started_at, iso_now(), 1, "feed not modified"),
        )
        conn.commit()
        return

    if not resp.ok:
        logger.error("feed fetch failed status=%s", resp.status_code)
        conn.execute(
            "INSERT INTO runs (run_type, started_at, finished_at, ok, summary) VALUES (?, ?, ?, ?, ?)",
            ("ingest", started_at, iso_now(), 0, f"feed fetch failed status={resp.status_code}"),
        )
        conn.commit()
        return

    if resp.ok:
        conn.execute(
            "INSERT INTO http_cache (url, etag, last_modified, last_fetched_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(url) DO UPDATE SET etag = excluded.etag, last_modified = excluded.last_modified, last_fetched_at = excluded.last_fetched_at",
            (
                cfg.tracker.feed_url,
                resp.headers.get("ETag"),
                resp.headers.get("Last-Modified"),
                iso_now(),
            ),
        )
        conn.commit()

    feed = feedparser.parse(resp.content)
    for entry in feed.entries:
        title = str(entry.get("title", "")).strip()
        topic_url = str(entry.get("link", "") or entry.get("id", "")).strip()
        if not topic_url:
            skipped_count += 1
            continue
        if not _allowed_by_filters(cfg, title, topic_url, entry):
            skipped_count += 1
            continue

        row = conn.execute(
            "SELECT * FROM torrents WHERE topic_url = ?",
            (topic_url,),
        ).fetchone()

        if row:
            conn.execute(
                "UPDATE torrents SET title = ?, last_seen_in_feed = ? WHERE id = ?",
                (title, iso_now(), row["id"]),
            )
        else:
            conn.execute(
                "INSERT INTO torrents (topic_url, title, discovered_at, last_seen_in_feed, status) VALUES (?, ?, ?, ?, ?)",
                (topic_url, title, iso_now(), iso_now(), "new"),
            )
            new_count += 1
        conn.commit()

        row = conn.execute(
            "SELECT * FROM torrents WHERE topic_url = ?",
            (topic_url,),
        ).fetchone()
        if not row:
            continue

        magnet_url, torrent_url = _extract_links_from_entry(entry)
        size_bytes = row["size_bytes"]
        if not size_bytes and entry.get("summary"):
            size_bytes = parse_size(str(entry.get("summary")))

        magnet_url = magnet_url or row["magnet_url"]
        torrent_url = torrent_url or row["torrent_url"]

        needs_fetch = cfg.tracker.html_parse_enabled and ((not magnet_url and not torrent_url) or not size_bytes)
        if needs_fetch:
            if not robots.allowed(topic_url):
                conn.execute(
                    "UPDATE torrents SET last_error = ? WHERE id = ?",
                    ("robots disallow", row["id"]),
                )
                conn.commit()
            else:
                cache_row = conn.execute(
                    "SELECT etag, last_modified, last_fetched_at FROM http_cache WHERE url = ?",
                    (topic_url,),
                ).fetchone()
                fetch_headers: Dict[str, str] = {}
                if cache_row:
                    if cache_row["etag"]:
                        fetch_headers["If-None-Match"] = cache_row["etag"]
                    if cache_row["last_modified"]:
                        fetch_headers["If-Modified-Since"] = cache_row["last_modified"]
                skip_fetch = False
                if cache_row and cache_row["last_fetched_at"]:
                    ttl_seconds = cfg.tracker.topic_cache_ttl_minutes * 60
                    try:
                        last = datetime.fromisoformat(cache_row["last_fetched_at"])
                        if last.tzinfo is None:
                            last = last.replace(tzinfo=timezone.utc)
                        if (datetime.now(timezone.utc) - last).total_seconds() < ttl_seconds:
                            skip_fetch = True
                    except ValueError:
                        pass
                if not skip_fetch:
                    limiter.wait()
                    page = session.get(topic_url, headers=fetch_headers, timeout=20)
                    if page.status_code == 304:
                        conn.execute(
                            "UPDATE http_cache SET last_fetched_at = ? WHERE url = ?",
                            (iso_now(), topic_url),
                        )
                        conn.commit()
                    elif page.ok:
                        magnet_html, torrent_html, size_html = _extract_from_html(cfg.tracker.base_url, page.text)
                        magnet_url = magnet_url or magnet_html
                        torrent_url = torrent_url or torrent_html
                        size_bytes = size_bytes or size_html
                        conn.execute(
                            "INSERT INTO http_cache (url, etag, last_modified, last_fetched_at) VALUES (?, ?, ?, ?) "
                            "ON CONFLICT(url) DO UPDATE SET etag = excluded.etag, last_modified = excluded.last_modified, last_fetched_at = excluded.last_fetched_at",
                            (
                                topic_url,
                                page.headers.get("ETag"),
                                page.headers.get("Last-Modified"),
                                iso_now(),
                            ),
                        )
                        conn.commit()

        if not magnet_url and not torrent_url:
            if not cfg.tracker.html_parse_enabled:
                err = "missing links; html_parse_disabled"
            else:
                err = "missing magnet/torrent link"
            conn.execute("UPDATE torrents SET last_error = ? WHERE id = ?", (err, row["id"]))
            conn.commit()
            continue

        infohash = row["infohash"] or (extract_infohash(magnet_url) if magnet_url else None)
        conn.execute(
            "UPDATE torrents SET magnet_url = ?, torrent_url = ?, size_bytes = ?, infohash = ?, last_error = NULL WHERE id = ?",
            (magnet_url, torrent_url, size_bytes, infohash, row["id"]),
        )
        conn.commit()

        if not row["porla_torrent_id"]:
            added = porla.add_torrent(magnet_url, torrent_url, cfg.porla.managed_tag)
            if added:
                conn.execute(
                    "UPDATE torrents SET porla_torrent_id = ?, porla_name = ?, added_to_porla_at = ?, status = ? WHERE id = ?",
                    (added.id, added.name, iso_now(), "queued", row["id"]),
                )
                conn.commit()
            else:
                conn.execute(
                    "UPDATE torrents SET last_error = ? WHERE id = ?",
                    ("porla add failed", row["id"]),
                )
                conn.commit()

    set_meta(conn, "last_ingest_at", iso_now())
    finished_at = iso_now()
    summary = f"new={new_count} skipped={skipped_count}"
    logger.info("ingest complete %s", summary)
    conn.execute(
        "INSERT INTO runs (run_type, started_at, finished_at, ok, summary) VALUES (?, ?, ?, ?, ?)",
        ("ingest", started_at, finished_at, 1, summary),
    )
    conn.commit()
