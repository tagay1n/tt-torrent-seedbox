"""Ingest queued torrents into Porla and mark them as added in the DB."""

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
from porla_client import PorlaClient
from util import iso_now, setup_logging

logger = setup_logging()


def run(config_path):
    config = load_config(config_path)
    http_session = build_session(config.porla.retry_count)

    # engine = get_engine(config.storage.db_path)
    # init_db(engine)
    db_session = get_session(config.storage.db_path)
    limiter = RateLimiter(min_interval=0.5)
    porla = PorlaClient(config.porla, http_session)

    login(config, http_session)
    ingested_count = 0
    for torrent in db_session.execute(select(Torrent).where(Torrent.status == "new")):
        torrent = torrent[0]
        logger.debug(f"Adding torrent '{torrent.title}' to porla")
        limiter.wait()
        info_hash = porla.add_torrent(title=torrent.title, torrent_url=torrent.torrent_url)
        if info_hash:
            torrent.infohash = info_hash
        torrent.status = "queued"
        torrent.added_to_porla_at = iso_now()
        db_session.commit()
        ingested_count += 1
        logger.debug(f"Added torrent '{torrent.title}' to porla")
    logger.debug(f"Ingested {ingested_count} torrents to porla")
