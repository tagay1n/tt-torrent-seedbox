from __future__ import annotations

import gzip
import html as html_lib
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple
from urllib.parse import urljoin

import feedparser
from dateutil import parser as date_parser

from ttseed.config import Config, load_config
from ttseed.db import connect, get_meta, init_db, set_meta
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


def _extract_links_from_entry(entry: Optional[Dict]) -> tuple[Optional[str], Optional[str]]:
    if not entry:
        return None, None
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


def _extract_title_from_html(html: str) -> Optional[str]:
    match = re.search(r"<title>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    if not match:
        return None
    title = re.sub(r"\\s+", " ", match.group(1)).strip()
    return html_lib.unescape(title) if title else None


def _strip_ns(tag: str) -> str:
    return tag.split("}", 1)[-1]


def _parse_lastmod(value: str) -> Optional[str]:
    try:
        dt = date_parser.isoparse(value)
    except (ValueError, TypeError):
        try:
            dt = date_parser.parse(value)
        except (ValueError, TypeError):
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _parse_sitemap(content: bytes) -> Tuple[list[Tuple[str, Optional[str]]], list[str]]:
    urls: list[Tuple[str, Optional[str]]] = []
    sitemaps: list[str] = []
    root = ET.fromstring(content)
    root_tag = _strip_ns(root.tag)
    if root_tag == "sitemapindex":
        for node in root:
            if _strip_ns(node.tag) != "sitemap":
                continue
            loc = None
            for child in node:
                if _strip_ns(child.tag) == "loc" and child.text:
                    loc = child.text.strip()
                    break
            if loc:
                sitemaps.append(loc)
    elif root_tag == "urlset":
        for node in root:
            if _strip_ns(node.tag) != "url":
                continue
            loc = None
            lastmod = None
            for child in node:
                tag = _strip_ns(child.tag)
                if tag == "loc" and child.text:
                    loc = child.text.strip()
                elif tag == "lastmod" and child.text:
                    lastmod = _parse_lastmod(child.text.strip())
            if loc:
                urls.append((loc, lastmod))
    return urls, sitemaps


def _maybe_decompress(url: str, resp) -> bytes:
    content = resp.content
    if url.endswith(".gz"):
        try:
            content = gzip.decompress(content)
        except OSError:
            return resp.content
    return content


def _fetch_cached(conn, session, limiter, url: str):
    headers: Dict[str, str] = {}
    cache = conn.execute(
        "SELECT etag, last_modified FROM http_cache WHERE url = ?",
        (url,),
    ).fetchone()
    if cache:
        if cache["etag"]:
            headers["If-None-Match"] = cache["etag"]
        if cache["last_modified"]:
            headers["If-Modified-Since"] = cache["last_modified"]
    limiter.wait()
    resp = session.get(url, headers=headers, timeout=20)
    if resp.status_code == 304:
        conn.execute(
            "UPDATE http_cache SET last_fetched_at = ? WHERE url = ?",
            (iso_now(), url),
        )
        conn.commit()
        return None
    if resp.ok:
        conn.execute(
            "INSERT INTO http_cache (url, etag, last_modified, last_fetched_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(url) DO UPDATE SET etag = excluded.etag, last_modified = excluded.last_modified, last_fetched_at = excluded.last_fetched_at",
            (url, resp.headers.get("ETag"), resp.headers.get("Last-Modified"), iso_now()),
        )
        conn.commit()
    return resp


def _upsert_torrent(conn, topic_url: str, title: Optional[str], discovered_at: Optional[str]) -> tuple[int, bool]:
    row = conn.execute("SELECT id, discovered_at FROM torrents WHERE topic_url = ?", (topic_url,)).fetchone()
    if row:
        if title:
            conn.execute("UPDATE torrents SET title = ? WHERE id = ?", (title, row["id"]))
        if discovered_at and not row["discovered_at"]:
            conn.execute("UPDATE torrents SET discovered_at = ? WHERE id = ?", (discovered_at, row["id"]))
        conn.execute("UPDATE torrents SET last_seen_in_feed = ? WHERE id = ?", (iso_now(), row["id"]))
        conn.commit()
        return row["id"], False
    conn.execute(
        "INSERT INTO torrents (topic_url, title, discovered_at, last_seen_in_feed, status) VALUES (?, ?, ?, ?, ?)",
        (topic_url, title, discovered_at or iso_now(), iso_now(), "new"),
    )
    conn.commit()
    new_row = conn.execute("SELECT id FROM torrents WHERE topic_url = ?", (topic_url,)).fetchone()
    return new_row["id"], True


def _process_topic(
    cfg: Config,
    conn,
    session,
    limiter: RateLimiter,
    robots: RobotsChecker,
    porla: PorlaClient,
    topic_url: str,
    title: Optional[str],
    entry: Optional[Dict],
    discovered_at: Optional[str] = None,
) -> bool:
    torrent_id, created = _upsert_torrent(conn, topic_url, title, discovered_at)
    row = conn.execute("SELECT * FROM torrents WHERE id = ?", (torrent_id,)).fetchone()

    magnet_url, torrent_url = _extract_links_from_entry(entry)
    size_bytes = row["size_bytes"]
    if entry and not size_bytes and entry.get("summary"):
        size_bytes = parse_size(str(entry.get("summary")))

    magnet_url = magnet_url or row["magnet_url"]
    torrent_url = torrent_url or row["torrent_url"]
    title = row["title"] or title

    needs_fetch = cfg.tracker.html_parse_enabled and (
        (not magnet_url and not torrent_url) or not size_bytes or not title
    )
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
                    magnet_html, torrent_html, size_html = _extract_from_html(
                        cfg.tracker.base_url, page.text
                    )
                    title_html = _extract_title_from_html(page.text)
                    magnet_url = magnet_url or magnet_html
                    torrent_url = torrent_url or torrent_html
                    size_bytes = size_bytes or size_html
                    title = title or title_html
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
        return created

    infohash = row["infohash"] or (extract_infohash(magnet_url) if magnet_url else None)
    conn.execute(
        "UPDATE torrents SET title = ?, magnet_url = ?, torrent_url = ?, size_bytes = ?, infohash = ?, last_error = NULL WHERE id = ?",
        (title, magnet_url, torrent_url, size_bytes, infohash, row["id"]),
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
    return created


def _sitemap_backfill(cfg: Config, conn, session, limiter, robots, porla, logger) -> int:
    tracker = cfg.tracker
    if not tracker.sitemap_backfill_enabled or not tracker.sitemap_url:
        return 0
    if not tracker.sitemap_backfill_force:
        if get_meta(conn, "sitemap_backfill_done"):
            logger.info("sitemap backfill already completed")
            return 0

    queue = [tracker.sitemap_url]
    seen = set()
    urls: list[Tuple[str, Optional[str]]] = []
    parsed_any = False

    while queue:
        sitemap_url = queue.pop(0)
        if sitemap_url in seen:
            continue
        seen.add(sitemap_url)
        if not robots.allowed(sitemap_url):
            logger.warning("robots disallow sitemap %s", sitemap_url)
            continue
        resp = _fetch_cached(conn, session, limiter, sitemap_url)
        if resp is None:
            continue
        if not resp.ok:
            logger.warning("sitemap fetch failed %s status=%s", sitemap_url, resp.status_code)
            continue
        content = _maybe_decompress(sitemap_url, resp)
        try:
            new_urls, nested = _parse_sitemap(content)
        except ET.ParseError:
            logger.warning("sitemap parse failed %s", sitemap_url)
            continue
        parsed_any = True
        queue.extend(nested)
        urls.extend(new_urls)

    added = 0
    patterns = tracker.sitemap_topic_regex
    processed = 0
    for topic_url, lastmod in urls:
        if patterns and not any_regex_match(patterns, topic_url):
            continue
        if tracker.sitemap_backfill_limit and processed >= tracker.sitemap_backfill_limit:
            break
        created = _process_topic(
            cfg=cfg,
            conn=conn,
            session=session,
            limiter=limiter,
            robots=robots,
            porla=porla,
            topic_url=topic_url,
            title=None,
            entry=None,
            discovered_at=lastmod,
        )
        processed += 1
        if created:
            added += 1

    if parsed_any:
        set_meta(conn, "sitemap_backfill_done", iso_now())
        logger.info("sitemap backfill completed added=%s", added)
    else:
        logger.warning("sitemap backfill did not parse any urls")
    return added


def run(config_path: str) -> None:
    logger = setup_logging()
    cfg = load_config(config_path)
    session = build_session(cfg.porla.retry_count)
    session.headers.update({"User-Agent": cfg.tracker.user_agent})

    conn = connect(cfg.storage.db_path)
    init_db(conn)

    robots = RobotsChecker(cfg.tracker.base_url, session, cfg.tracker.user_agent)
    base_interval = 1.0 / max(cfg.tracker.rate_limit_per_sec, 0.1)
    crawl_delay = robots.crawl_delay()
    if crawl_delay is not None and crawl_delay > base_interval:
        base_interval = crawl_delay
    limiter = RateLimiter(min_interval=base_interval)
    porla = PorlaClient(cfg.porla, session)

    started_at = iso_now()
    new_count = 0
    skipped_count = 0
    sitemap_added = _sitemap_backfill(cfg, conn, session, limiter, robots, porla, logger)

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
        summary = f"new=0 skipped=0 sitemap_added={sitemap_added} feed=not_modified"
        conn.execute(
            "INSERT INTO runs (run_type, started_at, finished_at, ok, summary) VALUES (?, ?, ?, ?, ?)",
            ("ingest", started_at, iso_now(), 1, summary),
        )
        conn.commit()
        return

    if not resp.ok:
        logger.error("feed fetch failed status=%s", resp.status_code)
        summary = f"new=0 skipped=0 sitemap_added={sitemap_added} feed_status={resp.status_code}"
        conn.execute(
            "INSERT INTO runs (run_type, started_at, finished_at, ok, summary) VALUES (?, ?, ?, ?, ?)",
            ("ingest", started_at, iso_now(), 0, summary),
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
        created = _process_topic(
            cfg=cfg,
            conn=conn,
            session=session,
            limiter=limiter,
            robots=robots,
            porla=porla,
            topic_url=topic_url,
            title=title,
            entry=entry,
        )
        if created:
            new_count += 1

    set_meta(conn, "last_ingest_at", iso_now())
    finished_at = iso_now()
    summary = f"new={new_count} skipped={skipped_count} sitemap_added={sitemap_added}"
    logger.info("ingest complete %s", summary)
    conn.execute(
        "INSERT INTO runs (run_type, started_at, finished_at, ok, summary) VALUES (?, ?, ?, ?, ?)",
        ("ingest", started_at, finished_at, 1, summary),
    )
    conn.commit()
