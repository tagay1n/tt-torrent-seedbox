"""Tracker discovery: crawl categories/topics or RSS feed and upsert torrents.

Handles login, polite fetching, and URL normalization for incoming topics.
"""

import re
from urllib.parse import urljoin

import feedparser
from bs4 import BeautifulSoup
from sqlalchemy import select

from config import load_config
from db import (
    Torrent,
    get_session,
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
    """Run full forum discovery workflow from categories down to topic pages."""
    config = load_config(config_path)
    http_session = build_session(config.porla.retry_count)

    db_session = get_session(config.storage.db_path)

    limiter = RateLimiter(min_interval=0.8)

    login(config, http_session)
    _parse(config, http_session, db_session, limiter)


def _parse(config, http_session, db_session, limiter):
    """Traverse categories and topics, parse each topic, and upsert DB rows."""
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
    """Parse top-level category links from the configured forum page."""
    url = urljoin(config.tracker.base_url, categories_path)
    resp = session.get(url, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, features="html.parser")
    categories_ul = soup.find("ul", {"class": "topiclist forums"})
    categories = categories_ul.find_all("a", {"class": "forumtitle"})
    return {c["href"]: c.text for c in categories}


def _parse_topics_in_category_page(config, session, category_path, limiter):
    """Collect all topic links in a category, following pagination."""
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
    """Parse torrent metadata from a topic page.

    Extracts and normalizes the torrent attachment URL, title, tracker-side
    size, and current seed/leech/download stats. Returns `None` when the topic
    does not expose a torrent download action.
    """
    url = urljoin(config.tracker.base_url, topic_path)
    limiter.wait()
    resp = session.get(url, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, features="html.parser")

    torrent_download_link_a = soup.find("a", string="Торрентны йөкләргә")
    if not torrent_download_link_a or not (
        torrent_download_link := torrent_download_link_a["href"]
    ):
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


def _upsert_torrent(new_torrent, db_session):
    """Insert or refresh a torrent row keyed by canonical topic URL."""
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


def feed(config_path: str) -> None:
    """Ingest only feed-discovered topics, then parse each new topic page."""
    config = load_config(config_path)
    http_session = build_session(config.porla.retry_count)
    db_session = get_session(config.storage.db_path)
    limiter = RateLimiter(min_interval=0.8)

    login(config, http_session)

    resp = http_session.get(config.tracker.feed_url, timeout=20)
    resp.raise_for_status()
    parsed = feedparser.parse(resp.content)

    new_count = 0
    skipped = 0
    for entry in parsed.entries:
        title = str(entry.get("title", "")).strip()
        link = str(entry.get("link")).strip()
        if not link:
            skipped += 1
            continue
        topic_url = urljoin(config.tracker.base_url, link)
        normalized = normalize_topic_url(topic_url)
        exists = db_session.execute(
            select(Torrent).where(Torrent.topic_url == normalized)
        ).scalar_one_or_none()
        if exists:
            skipped += 1
            continue
        torrent = _parse_topic(config, http_session, title, topic_url, limiter)
        if torrent:
            _upsert_torrent(torrent, db_session)
            new_count += 1
    logger.debug("Feed done new=%s skipped=%s", new_count, skipped)
