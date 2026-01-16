from __future__ import annotations

import os
import sqlite3

from sqlalchemy import (
    Column,
    Float,
    Integer,
    Text,
    create_engine,
    event,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

SCHEMA_VERSION = 1

Base = declarative_base()


class Torrent(Base):
    """ORM model for tracked torrents."""

    __tablename__ = "torrents"

    id = Column(Integer, primary_key=True)
    topic_url = Column(Text, unique=True, nullable=False)
    title = Column(Text)
    discovered_at = Column(Text)
    last_seen_in_feed = Column(Text)
    magnet_url = Column(Text)
    torrent_url = Column(Text)
    infohash = Column(Text)
    size_bytes = Column(Integer)
    porla_torrent_id = Column(Text)
    porla_name = Column(Text)
    added_to_porla_at = Column(Text)
    last_stats_at = Column(Text)
    seeders = Column(Integer)
    leechers = Column(Integer)
    downloaded = Column(Integer)
    score = Column(Float)
    status = Column(Text)
    last_error = Column(Text)
    topic_last_fetched_at = Column(Text)
    topic_etag = Column(Text)
    topic_last_modified = Column(Text)

    def __repr__(self):
        return f"<Torrent(id={self.id}, title={self.title}, status={self.status})>"


_ENGINE_CACHE: dict[str, Engine] = {}


def get_engine(db_path: str) -> Engine:
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    if db_path not in _ENGINE_CACHE:
        engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})

        @event.listens_for(engine, "connect")
        def _set_sqlite_pragma(dbapi_connection, _):  # type: ignore[no-untyped-def]
            if isinstance(dbapi_connection, sqlite3.Connection):
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.close()

        _ENGINE_CACHE[db_path] = engine
    return _ENGINE_CACHE[db_path]


def get_session(db_path: str) -> Session:
    engine = get_engine(db_path)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    return factory()


def init_db(engine: Engine) -> None:
    Base.metadata.create_all(engine)
