import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from sqlalchemy import select

from config import load_config
from db import (
    Torrent,
    # get_engine,
    get_session,
    # init_db,
)
from http_client import RateLimiter, build_session
from login import login
from util import (
    iso_now,
    normalize_topic_url,
    parse_size,
    setup_logging,
)

MAGNET_HREF_RE = re.compile(r"magnet:\?[^\"'\s]+", re.IGNORECASE)
HREF_RE = re.compile(r"href=[\"']([^\"']+)[\"']", re.IGNORECASE)


logger = setup_logging()


def run(config_path: str) -> None:
    config = load_config(config_path)
    http_session = build_session(config.porla.retry_count)

    # engine = get_engine(config.storage.db_path)
    # init_db(engine)
    db_session = get_session(config.storage.db_path)

    limiter = RateLimiter(min_interval=0.8)

    login(config, http_session)
    _parse(config, http_session, db_session, limiter)


def _parse(config, http_session, db_session, limiter):
    categories = _parse_categories_page(config, http_session)
    logger.debug(f"Found {len(categories)} categories for parsing")
    for category_path, category_name in categories.items():
        logger.debug(f"Parsing category '{category_name}'({category_path})")

        topics = _parse_topics_in_category_page(config, http_session, category_path, limiter)
        if not topics:
            logger.debug(f"Category '{category_name}' has no topics, skipping it...")
            continue

        logger.debug(f"Found {len(topics)} topics in category '{category_name}'")
        for topic_path, topic_name in topics.items():
            logger.debug(
                f"--> Parsing topic '{topic_name}'({topic_path}) in category '{category_name}'"
            )
            if torrent := _parse_topic(config, http_session, topic_name, topic_path, limiter):
                _upsert_torrent(torrent, db_session)
                logger.debug(f"--> Parsed topic '{topic_name}'")


def _parse_categories_page(config, session, categories_path="/viewforum.php?f=49"):
    url = urljoin(config.tracker.base_url, categories_path)
    resp = session.get(url, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, features="html.parser")
    categories_ul = soup.find("ul", {"class": "topiclist forums"})
    categories = categories_ul.find_all("a", {"class": "forumtitle"})
    return {c["href"]: c.text for c in categories}


def _parse_topics_in_category_page(config, session, category_path, limiter):
    result = {}
    url = urljoin(config.tracker.base_url, category_path)
    while True:
        limiter.wait()
        resp = session.get(url, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, features="html.parser")
        topics_div = [
            c for c in soup.find_all("div", {"class": "forumbg"}) if c.find("dt", string="Темалар")
        ]
        if len(topics_div) == 0:
            return result
        elif len(topics_div) > 1:
            raise ValueError(
                f"Expected at least one div with topics, actually it was {len(topics_div)}"
            )
        topics = topics_div[0].find_all("a", {"class": "topictitle"})
        result.update({t["href"]: t.text for t in topics})

        if pagination := soup.select_one("div.pagination"):
            cur_page = int(pagination.select_one("strong").text)
            if next_page := pagination.find("a", string=str(cur_page + 1)):
                url = urljoin(config.tracker.base_url, next_page["href"])
                logger.debug(f"Found next page url in category: {url}")
                continue
        break
    return result


def _parse_topic(config, session, topic_name, topic_path, limiter):
    url = urljoin(config.tracker.base_url, topic_path)
    limiter.wait()
    resp = session.get(url, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, features="html.parser")

    torrent_download_link_a = soup.find("a", string="Торрентны йөкләргә")
    if not torrent_download_link_a or not (torrent_download_link := torrent_download_link_a["href"]):
        logger.warning(f"Topic {topic_name}({topic_path}) does not have torrent url")
        return None

    torrent = Torrent()
    torrent.topic_url = normalize_topic_url(url)
    torrent.title = topic_name or soup.select_one("h2 a").text
    torrent.discovered_at = iso_now()
    torrent.torrent_url = normalize_topic_url(
        urljoin(config.tracker.base_url, torrent_download_link)
    )
    torrent.status = "new"

    sl = soup.select_one("div.torrent_sl table")
    torrent.size_bytes = parse_size(
        next(c for c in sl.find_all("td") if c.find("b", string="Күләме")).text
    )
    torrent.seeders = int(sl.select_one("span.seed").text)
    torrent.leechers = int(sl.select_one("span.leech").text)
    torrent.downloaded = int(sl.select_one("span.complet").text)

    return torrent


# def _entry_tags(entry: dict) -> list[str]:
#     tags = []
#     for tag in entry.get("tags", []) or []:
#         term = tag.get("term") if isinstance(tag, dict) else None
#         if term:
#             tags.append(str(term))
#     return tags


# def _allowed_by_filters(cfg: Config, title: str, topic_url: str, entry: dict) -> bool:
#     tracker = cfg.tracker
#     if tracker.allow_forums:
#         forum_id = parse_forum_id(topic_url)
#         if forum_id not in tracker.allow_forums:
#             return False
#     if tracker.allow_tags:
#         tags = _entry_tags(entry)
#         if not any(tag in tracker.allow_tags for tag in tags):
#             return False
#     if tracker.allow_regex_title:
#         if not any_regex_match(tracker.allow_regex_title, title):
#             return False
#     return True


# def _extract_links_from_entry(entry: dict | None) -> tuple[str | None, str | None]:
#     if not entry:
#         return None, None
#     magnet_url = None
#     torrent_url = None
#     for link in entry.get("links", []) or []:
#         href = link.get("href") if isinstance(link, dict) else None
#         if not href:
#             continue
#         if href.startswith("magnet:"):
#             magnet_url = href
#         if href.endswith(".torrent"):
#             torrent_url = href
#     summary = entry.get("summary", "") or ""
#     if not magnet_url:
#         match = MAGNET_HREF_RE.search(summary)
#         if match:
#             magnet_url = match.group(0)
#     return magnet_url, torrent_url


# def _extract_from_html(
#     base_url: str, html: str
# ) -> tuple[str | None, str | None, int | None]:
#     magnet_url = None
#     torrent_url = None
#     size_bytes = parse_size(html)
#     match = MAGNET_HREF_RE.search(html)
#     if match:
#         magnet_url = match.group(0)
#     for href in HREF_RE.findall(html):
#         if href.startswith("magnet:"):
#             magnet_url = href
#             continue
#         if ".torrent" in href or "download/file.php" in href:
#             torrent_url = urljoin(base_url, href)
#     return magnet_url, torrent_url, size_bytes


# def _extract_title_from_html(html: str) -> str | None:
#     match = re.search(r"<title>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
#     if not match:
#         return None
#     title = re.sub(r"\\s+", " ", match.group(1)).strip()
#     return html_lib.unescape(title) if title else None


# def _strip_ns(tag: str) -> str:
#     return tag.split("}", 1)[-1]


# def _parse_lastmod(value: str) -> str | None:
#     try:
#         dt = date_parser.isoparse(value)
#     except (ValueError, TypeError):
#         try:
#             dt = date_parser.parse(value)
#         except (ValueError, TypeError):
#             return None
#     if dt.tzinfo is None:
#         dt = dt.replace(tzinfo=timezone.utc)
#     return dt.astimezone(timezone.utc).isoformat()


# def _parse_sitemap(content: bytes) -> tuple[list[tuple[str, str | None]], list[str]]:
#     urls: list[tuple[str, str | None]] = []
#     sitemaps: list[str] = []
#     root = ET.fromstring(content)
#     root_tag = _strip_ns(root.tag)
#     if root_tag == "sitemapindex":
#         for node in root:
#             if _strip_ns(node.tag) != "sitemap":
#                 continue
#             loc = None
#             for child in node:
#                 if _strip_ns(child.tag) == "loc" and child.text:
#                     loc = child.text.strip()
#                     break
#             if loc:
#                 sitemaps.append(loc)
#     elif root_tag == "urlset":
#         for node in root:
#             if _strip_ns(node.tag) != "url":
#                 continue
#             loc = None
#             lastmod = None
#             for child in node:
#                 tag = _strip_ns(child.tag)
#                 if tag == "loc" and child.text:
#                     loc = child.text.strip()
#                 elif tag == "lastmod" and child.text:
#                     lastmod = _parse_lastmod(child.text.strip())
#             if loc:
#                 urls.append((loc, lastmod))
#     return urls, sitemaps


# def _maybe_decompress(url: str, resp) -> bytes:
#     content = resp.content
#     if url.endswith(".gz"):
#         try:
#             content = gzip.decompress(content)
#         except OSError:
#             return resp.content
#     return content


# def _fetch_cached(session_db, session, limiter, url: str, use_cache_headers: bool = True):
#     headers: dict[str, str] = {}
#     cache = None
#     if use_cache_headers:
#         cache = session_db.get(HttpCache, url)
#         if cache:
#             if cache.etag:
#                 headers["If-None-Match"] = cache.etag
#             if cache.last_modified:
#                 headers["If-Modified-Since"] = cache.last_modified
#     limiter.wait()
#     resp = session.get(url, headers=headers, timeout=20)
#     if resp.status_code == 304:
#         if cache:
#             cache.last_fetched_at = iso_now()
#         else:
#             session_db.add(HttpCache(url=url, last_fetched_at=iso_now()))
#         session_db.commit()
#         return None
#     if resp.ok:
#         if not cache:
#             cache = HttpCache(url=url)
#             session_db.add(cache)
#         cache.etag = resp.headers.get("ETag")
#         cache.last_modified = resp.headers.get("Last-Modified")
#         cache.last_fetched_at = iso_now()
#         session_db.commit()
#     return resp


# def _load_local_sitemap_bytes(sitemap_url: str) -> bytes | None:
#     parsed = urlparse(sitemap_url)
#     if parsed.scheme == "file":
#         path = parsed.path
#     elif parsed.scheme == "":
#         path = sitemap_url
#     else:
#         return None
#     if not path:
#         return None
#     if not os.path.exists(path):
#         return None
#     with open(path, "rb") as handle:
#         return handle.read()


def _upsert_torrent(new_torrent, db_session):
    torrent = db_session.execute(
        select(Torrent).where(Torrent.topic_url == new_torrent.topic_url)
    ).scalar_one_or_none()
    if torrent:
        torrent.title = new_torrent.title
        torrent.torrent_url = new_torrent.torrent_url
        torrent.size_bytes = new_torrent.size_bytes
        torrent.seeders = new_torrent.seeders
        torrent.leechers = new_torrent.leechers
        torrent.downloaded = new_torrent.downloaded

        if not torrent.discovered_at:
            torrent.discovered_at = new_torrent.discovered_at
        if not torrent.status:
            torrent.status = new_torrent.status

    else:
        torrent = new_torrent

    db_session.add(torrent)
    db_session.commit()


# def _upsert_torrent2(
#     session_db, topic_url: str, title: str | None, discovered_at: str | None
# ) -> tuple[int, bool]:
#     normalized_url = normalize_topic_url(topic_url)
#     row = session_db.execute(
#         select(Torrent).where(Torrent.topic_url == normalized_url)
#     ).scalar_one_or_none()
#     if not row and normalized_url != topic_url:
#         row = session_db.execute(
#             select(Torrent).where(Torrent.topic_url == topic_url)
#         ).scalar_one_or_none()
#         if row:
#             existing_norm = session_db.execute(
#                 select(Torrent).where(Torrent.topic_url == normalized_url)
#             ).scalar_one_or_none()
#             if not existing_norm:
#                 row.topic_url = normalized_url
#                 session_db.commit()
#             topic_url = normalized_url
#     else:
#         topic_url = normalized_url

#     if row:
#         if title:
#             row.title = title
#         if discovered_at and not row.discovered_at:
#             row.discovered_at = discovered_at
#         row.last_seen_in_feed = iso_now()
#         session_db.commit()
#         return row.id, False

#     torrent = Torrent(
#         topic_url=topic_url,
#         title=title,
#         discovered_at=discovered_at or iso_now(),
#         last_seen_in_feed=iso_now(),
#         status="new",
#     )
#     session_db.add(torrent)
#     session_db.commit()
#     return torrent.id, True


# def _process_topic(
#     cfg: Config,
#     session_db,
#     session,
#     limiter: RateLimiter,
#     robots: RobotsChecker,
#     porla: PorlaClient,
#     topic_url: str,
#     title: str | None,
#     entry: dict | None,
#     discovered_at: str | None = None,
# ) -> bool:
#     topic_url = normalize_topic_url(topic_url)
#     torrent_id, created = _upsert_torrent(session_db, topic_url, title, discovered_at)
#     row = session_db.get(Torrent, torrent_id)

#     magnet_url, torrent_url = _extract_links_from_entry(entry)
#     size_bytes = row.size_bytes
#     if entry and not size_bytes and entry.get("summary"):
#         size_bytes = parse_size(str(entry.get("summary")))

#     magnet_url = magnet_url or row.magnet_url
#     torrent_url = torrent_url or row.torrent_url
#     title = row.title or title

#     needs_fetch = cfg.tracker.html_parse_enabled and (
#         (not magnet_url and not torrent_url) or not size_bytes or not title
#     )
#     if needs_fetch:
#         if not robots.allowed(topic_url):
#             row.last_error = "robots disallow"
#             session_db.commit()
#         else:
#             cache_row = session_db.get(HttpCache, topic_url)
#             fetch_headers: dict[str, str] = {}
#             if cache_row:
#                 if cache_row.etag:
#                     fetch_headers["If-None-Match"] = cache_row.etag
#                 if cache_row.last_modified:
#                     fetch_headers["If-Modified-Since"] = cache_row.last_modified
#             skip_fetch = False
#             if cache_row and cache_row.last_fetched_at:
#                 ttl_seconds = cfg.tracker.topic_cache_ttl_minutes * 60
#                 try:
#                     last = datetime.fromisoformat(cache_row.last_fetched_at)
#                     if last.tzinfo is None:
#                         last = last.replace(tzinfo=timezone.utc)
#                     if (datetime.now(timezone.utc) - last).total_seconds() < ttl_seconds:
#                         skip_fetch = True
#                 except ValueError:
#                     pass
#             if not skip_fetch:
#                 limiter.wait()
#                 page = session.get(topic_url, headers=fetch_headers, timeout=20)
#                 if page.status_code == 304:
#                     if cache_row:
#                         cache_row.last_fetched_at = iso_now()
#                     else:
#                         session_db.add(HttpCache(url=topic_url, last_fetched_at=iso_now()))
#                     session_db.commit()
#                 elif page.ok:
#                     magnet_html, torrent_html, size_html = _extract_from_html(
#                         cfg.tracker.base_url, page.text
#                     )
#                     title_html = _extract_title_from_html(page.text)
#                     magnet_url = magnet_url or magnet_html
#                     torrent_url = torrent_url or torrent_html
#                     size_bytes = size_bytes or size_html
#                     title = title or title_html
#                     if not cache_row:
#                         cache_row = HttpCache(url=topic_url)
#                         session_db.add(cache_row)
#                     cache_row.etag = page.headers.get("ETag")
#                     cache_row.last_modified = page.headers.get("Last-Modified")
#                     cache_row.last_fetched_at = iso_now()
#                     session_db.commit()

#     if not magnet_url and not torrent_url:
#         if not cfg.tracker.html_parse_enabled:
#             err = "missing links; html_parse_disabled"
#         else:
#             err = "missing magnet/torrent link"
#         row.last_error = err
#         session_db.commit()
#         return created

#     infohash = row.infohash or (extract_infohash(magnet_url) if magnet_url else None)
#     row.title = title
#     row.magnet_url = magnet_url
#     row.torrent_url = torrent_url
#     row.size_bytes = size_bytes
#     row.infohash = infohash
#     row.last_error = None
#     session_db.commit()

#     if not row.porla_torrent_id:
#         added = porla.add_torrent(magnet_url, torrent_url, cfg.porla.managed_tag)
#         if added:
#             row.porla_torrent_id = added.id
#             row.porla_name = added.name
#             row.added_to_porla_at = iso_now()
#             row.status = "queued"
#             session_db.commit()
#         else:
#             row.last_error = "porla add failed"
#             session_db.commit()
#     return created


# def _sitemap_backfill(cfg: Config, session_db, session, limiter, robots, porla, logger) -> int:
#     tracker = cfg.tracker
#     if not tracker.sitemap_backfill_enabled or not tracker.sitemap_url:
#         return 0
#     if not tracker.sitemap_backfill_force:
#         if get_meta(session_db, "sitemap_backfill_done"):
#             logger.debug("sitemap backfill already completed")
#             return 0

#     queue = []
#     seen = set()
#     urls: list[tuple[str, str | None]] = []
#     parsed_any = False

#     local_bytes = _load_local_sitemap_bytes(tracker.sitemap_url)
#     if local_bytes is not None:
#         try:
#             new_urls, nested = _parse_sitemap(local_bytes)
#         except ET.ParseError:
#             logger.warning("local sitemap parse failed %s", tracker.sitemap_url)
#         else:
#             parsed_any = True
#             urls.extend(new_urls)
#             queue.extend(nested)
#     else:
#         queue.append(tracker.sitemap_url)

#     while queue:
#         sitemap_url = queue.pop(0)
#         if sitemap_url in seen:
#             continue
#         seen.add(sitemap_url)
#         if not robots.allowed(sitemap_url):
#             logger.warning("robots disallow sitemap %s", sitemap_url)
#             continue
#         resp = _fetch_cached(session_db, session, limiter, sitemap_url, use_cache_headers=False)
#         if resp is None:
#             continue
#         if not resp.ok:
#             logger.warning("sitemap fetch failed %s status=%s", sitemap_url, resp.status_code)
#             continue
#         content = _maybe_decompress(sitemap_url, resp)
#         try:
#             new_urls, nested = _parse_sitemap(content)
#         except ET.ParseError:
#             logger.warning("sitemap parse failed %s", sitemap_url)
#             continue
#         parsed_any = True
#         queue.extend(nested)
#         urls.extend(new_urls)

#     added = 0
#     matched = 0
#     patterns = tracker.sitemap_topic_regex
#     processed = 0
#     logger.debug("sitemap urls discovered=%s", len(urls))
#     for topic_url, lastmod in urls:
#         topic_url = normalize_topic_url(topic_url)
#         if patterns and not any_regex_match(patterns, topic_url):
#             continue
#         matched += 1
#         if tracker.sitemap_backfill_limit and processed >= tracker.sitemap_backfill_limit:
#             break
#         created = _process_topic(
#             cfg=cfg,
#             session_db=session_db,
#             session=session,
#             limiter=limiter,
#             robots=robots,
#             porla=porla,
#             topic_url=topic_url,
#             title=None,
#             entry=None,
#             discovered_at=lastmod,
#         )
#         processed += 1
#         if created:
#             added += 1

#     if parsed_any:
#         set_meta(session_db, "sitemap_backfill_done", iso_now())
#         logger.debug(
#             "sitemap backfill completed total=%s matched=%s processed=%s added=%s",
#             len(urls),
#             matched,
#             processed,
#             added,
#         )
#     else:
#         logger.warning("sitemap backfill did not parse any urls")
#     return added


# def run2(config_path: str) -> None:
#     logger = setup_logging()
#     cfg = load_config(config_path)
#     session = build_session(cfg.porla.retry_count)
#     session.headers.update({"User-Agent": cfg.tracker.user_agent})

#     engine = get_engine(cfg.storage.db_path)
#     init_db(engine)
#     session_db = get_session(cfg.storage.db_path)

#     robots = RobotsChecker(cfg.tracker.base_url, session, cfg.tracker.user_agent)
#     base_interval = 1.0 / max(cfg.tracker.rate_limit_per_sec, 0.1)
#     crawl_delay = robots.crawl_delay()
#     if crawl_delay is not None and crawl_delay > base_interval:
#         base_interval = crawl_delay
#     limiter = RateLimiter(min_interval=base_interval)
#     porla = PorlaClient(cfg.porla, session)

#     started_at = iso_now()
#     new_count = 0
#     skipped_count = 0
#     _login(cfg, session, limiter, robots, logger)
#     sitemap_added = _sitemap_backfill(cfg, session_db, session, limiter, robots, porla, logger)

#     feed_headers = {}
#     feed_cache = session_db.get(HttpCache, cfg.tracker.feed_url)
#     if feed_cache:
#         if feed_cache.etag:
#             feed_headers["If-None-Match"] = feed_cache.etag
#         if feed_cache.last_modified:
#             feed_headers["If-Modified-Since"] = feed_cache.last_modified

#     limiter.wait()
#     resp = session.get(cfg.tracker.feed_url, headers=feed_headers, timeout=20)
#     if resp.status_code == 304:
#         logger.debug("feed not modified")
#         set_meta(session_db, "last_ingest_at", iso_now())
#         summary = f"new=0 skipped=0 sitemap_added={sitemap_added} feed=not_modified"
#         record_run(session_db, "ingest", started_at, iso_now(), True, summary)
#         session_db.close()
#         return

#     if not resp.ok:
#         logger.error("feed fetch failed status=%s", resp.status_code)
#         summary = f"new=0 skipped=0 sitemap_added={sitemap_added} feed_status={resp.status_code}"
#         record_run(session_db, "ingest", started_at, iso_now(), False, summary)
#         session_db.close()
#         return

#     if resp.ok:
#         if not feed_cache:
#             feed_cache = HttpCache(url=cfg.tracker.feed_url)
#             session_db.add(feed_cache)
#         feed_cache.etag = resp.headers.get("ETag")
#         feed_cache.last_modified = resp.headers.get("Last-Modified")
#         feed_cache.last_fetched_at = iso_now()
#         session_db.commit()

#     feed = feedparser.parse(resp.content)
#     for entry in feed.entries:
#         title = str(entry.get("title", "")).strip()
#         topic_url = str(entry.get("link", "") or entry.get("id", "")).strip()
#         if not topic_url:
#             skipped_count += 1
#             continue
#         if not _allowed_by_filters(cfg, title, topic_url, entry):
#             skipped_count += 1
#             continue
#         created = _process_topic(
#             cfg=cfg,
#             session_db=session_db,
#             session=session,
#             limiter=limiter,
#             robots=robots,
#             porla=porla,
#             topic_url=topic_url,
#             title=title,
#             entry=entry,
#         )
#         if created:
#             new_count += 1

#     set_meta(session_db, "last_ingest_at", iso_now())
#     finished_at = iso_now()
#     summary = f"new={new_count} skipped={skipped_count} sitemap_added={sitemap_added}"
#     logger.debug("ingest complete %s", summary)
#     record_run(session_db, "ingest", started_at, finished_at, True, summary)
#     session_db.close()
