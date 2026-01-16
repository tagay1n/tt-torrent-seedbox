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
    select,
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


# class TrackerEndpoint(Base):
#     """ORM model for tracker scrape stats per torrent+tracker URL."""
#     __tablename__ = "tracker_endpoints"
#     __table_args__ = (UniqueConstraint("torrent_id", "tracker_url", name="uq_tracker_endpoint"),)

#     id = Column(Integer, primary_key=True)
#     torrent_id = Column(Integer, ForeignKey("torrents.id", ondelete="CASCADE"), nullable=False)
#     tracker_url = Column(Text, nullable=False)
#     last_scrape_at = Column(Text)
#     scrape_complete = Column(Integer)
#     scrape_incomplete = Column(Integer)
#     scrape_downloaded = Column(Integer)
#     scrape_status = Column(Text)
#     last_error = Column(Text)

#     torrent = relationship("Torrent", back_populates="tracker_endpoints")


# class Run(Base):
#     """ORM model for ingest/stats/reconcile run records."""
#     __tablename__ = "runs"

#     id = Column(Integer, primary_key=True)
#     run_type = Column(Text, nullable=False)
#     started_at = Column(Text)
#     finished_at = Column(Text)
#     ok = Column(Boolean)
#     summary = Column(Text)


# class ReconcileAction(Base):
#     """ORM model for reconcile actions (add/remove/skip/error)."""
#     __tablename__ = "reconcile_actions"

#     id = Column(Integer, primary_key=True)
#     torrent_id = Column(Integer, ForeignKey("torrents.id", ondelete="SET NULL"))
#     action = Column(Text, nullable=False)
#     reason = Column(Text)
#     created_at = Column(Text)


# class Meta(Base):
#     """ORM model for key/value metadata (schema version, last run timestamps)."""
#     __tablename__ = "meta"

#     key = Column(Text, primary_key=True)
#     value = Column(Text)


# class HttpCache(Base):
#     """ORM model for HTTP cache (ETag/Last-Modified)."""
#     __tablename__ = "http_cache"

#     url = Column(Text, primary_key=True)
#     etag = Column(Text)
#     last_modified = Column(Text)
#     last_fetched_at = Column(Text)


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
    with Session(engine) as session:
        existing = session.execute(
            select(Meta).where(Meta.key == "schema_version")
        ).scalar_one_or_none()
        if not existing:
            session.add(Meta(key="schema_version", value=str(SCHEMA_VERSION)))
            session.commit()


# def get_meta(session: Session, key: str) -> Optional[str]:
#     row = session.execute(select(Meta).where(Meta.key == key)).scalar_one_or_none()
#     return row.value if row else None


# def set_meta(session: Session, key: str, value: str) -> None:
#     row = session.execute(select(Meta).where(Meta.key == key)).scalar_one_or_none()
#     if row:
#         row.value = value
#     else:
#         session.add(Meta(key=key, value=value))
#     session.commit()


# def record_run(
#     session: Session,
#     run_type: str,
#     started_at: str,
#     finished_at: str,
#     ok: bool,
#     summary: str,
# ) -> None:
#     session.add(
#         Run(
#             run_type=run_type,
#             started_at=started_at,
#             finished_at=finished_at,
#             ok=ok,
#             summary=summary,
#         )
#     )
#     session.commit()


# def record_action(
#     session: Session,
#     torrent_id: Optional[int],
#     action: str,
#     reason: str,
#     created_at: str,
# ) -> None:
#     session.add(
#         ReconcileAction(
#             torrent_id=torrent_id,
#             action=action,
#             reason=reason,
#             created_at=created_at,
#         )
#     )
#     session.commit()
