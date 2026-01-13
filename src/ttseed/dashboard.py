from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Dict, List

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ttseed.config import load_config
from ttseed.db import connect, get_meta, init_db
from ttseed.http_client import build_session
from ttseed.porla_client import PorlaClient
from ttseed.util import load_pinned_list


def create_app(config_path: str) -> FastAPI:
    cfg = load_config(config_path)
    session = build_session(cfg.porla.retry_count)
    porla = PorlaClient(cfg.porla, session)

    app = FastAPI()
    app.mount("/static", StaticFiles(directory="static"), name="static")
    templates = Jinja2Templates(directory="templates")

    def get_conn():
        conn = connect(cfg.storage.db_path)
        init_db(conn)
        return conn

    def disk_usage() -> Dict[str, int]:
        path = os.path.dirname(cfg.storage.db_path) or "."
        stats = os.statvfs(path)
        total = stats.f_frsize * stats.f_blocks
        free = stats.f_frsize * stats.f_bavail
        used = total - free
        return {"total": total, "free": free, "used": used}

    @app.get("/healthz")
    def healthz() -> Dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    def readyz() -> Dict[str, str]:
        try:
            conn = get_conn()
            conn.execute("SELECT 1")
            conn.close()
        except Exception:
            return {"status": "db_error"}
        porla_ok = porla.health()
        return {"status": "ok" if porla_ok else "porla_error"}

    def _to_epoch(ts: str | None) -> int:
        if not ts:
            return 0
        try:
            dt = datetime.fromisoformat(ts)
        except ValueError:
            return 0
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())

    @app.get("/metrics")
    def metrics() -> PlainTextResponse:
        conn = get_conn()
        torrents_total = conn.execute("SELECT COUNT(*) AS c FROM torrents").fetchone()["c"]
        managed_total = conn.execute(
            "SELECT COUNT(*) AS c FROM torrents WHERE porla_torrent_id IS NOT NULL"
        ).fetchone()["c"]
        critical = conn.execute(
            "SELECT COUNT(*) AS c FROM torrents WHERE seeders <= 1 AND leechers > 0"
        ).fetchone()["c"]
        last_ingest = get_meta(conn, "last_ingest_at")
        last_stats = get_meta(conn, "last_stats_at")
        last_reconcile = get_meta(conn, "last_reconcile_at")
        since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        errors_last_24h = conn.execute(
            "SELECT COUNT(*) AS c FROM runs WHERE ok = 0 AND finished_at >= ?",
            (since,),
        ).fetchone()["c"]
        conn.close()
        usage = disk_usage()
        lines = [
            f"last_ingest_ok {_to_epoch(last_ingest)}",
            f"last_stats_ok {_to_epoch(last_stats)}",
            f"last_reconcile_ok {_to_epoch(last_reconcile)}",
            f"db_torrents_total {torrents_total}",
            f"porla_managed_total {managed_total}",
            f"vulnerable_critical_count {critical}",
            f"disk_used_bytes {usage['used']}",
            f"disk_free_bytes {usage['free']}",
            f"errors_last_24h {errors_last_24h}",
        ]
        return PlainTextResponse("\n".join(lines) + "\n")

    @app.get("/", response_class=HTMLResponse)
    def overview(request: Request):
        conn = get_conn()
        torrents_total = conn.execute("SELECT COUNT(*) AS c FROM torrents").fetchone()["c"]
        status_counts = conn.execute(
            "SELECT status, COUNT(*) AS c FROM torrents GROUP BY status ORDER BY c DESC"
        ).fetchall()
        critical = conn.execute(
            "SELECT COUNT(*) AS c FROM torrents WHERE seeders <= 1 AND leechers > 0"
        ).fetchone()["c"]
        last_runs = conn.execute(
            "SELECT run_type, MAX(finished_at) AS finished_at FROM runs GROUP BY run_type"
        ).fetchall()
        conn.close()
        usage = disk_usage()
        porla_ok = porla.health()
        return templates.TemplateResponse(
            "overview.html",
            {
                "request": request,
                "active": "overview",
                "torrents_total": torrents_total,
                "status_counts": status_counts,
                "critical": critical,
                "last_runs": last_runs,
                "porla_ok": porla_ok,
                "usage": usage,
                "auto_refresh": cfg.server.auto_refresh_seconds,
            },
        )

    @app.get("/vulnerable", response_class=HTMLResponse)
    def vulnerable(request: Request, critical: int = 0):
        conn = get_conn()
        base_query = "SELECT * FROM torrents"
        clauses: List[str] = []
        params: List[int] = []
        if critical:
            clauses.append("seeders <= 1 AND leechers > 0")
        if clauses:
            base_query += " WHERE " + " AND ".join(clauses)
        base_query += " ORDER BY score IS NULL, score DESC LIMIT 200"
        rows = conn.execute(base_query, params).fetchall()
        conn.close()
        pinned_set = load_pinned_list(cfg.policy.pinned_list_path)
        return templates.TemplateResponse(
            "vulnerable.html",
            {
                "request": request,
                "active": "vulnerable",
                "rows": rows,
                "pinned_set": pinned_set,
                "auto_refresh": cfg.server.auto_refresh_seconds,
            },
        )

    @app.get("/trackers", response_class=HTMLResponse)
    def trackers(request: Request):
        conn = get_conn()
        rows = conn.execute(
            "SELECT t.title, t.topic_url, e.tracker_url, e.scrape_complete, e.scrape_incomplete, e.scrape_downloaded, e.scrape_status, e.last_scrape_at "
            "FROM tracker_endpoints e JOIN torrents t ON t.id = e.torrent_id ORDER BY e.last_scrape_at DESC LIMIT 200"
        ).fetchall()
        conn.close()
        return templates.TemplateResponse(
            "trackers.html",
            {
                "request": request,
                "active": "trackers",
                "rows": rows,
                "auto_refresh": cfg.server.auto_refresh_seconds,
            },
        )

    @app.get("/actions", response_class=HTMLResponse)
    def actions(request: Request):
        conn = get_conn()
        rows = conn.execute(
            "SELECT a.created_at, a.action, a.reason, t.title, t.topic_url "
            "FROM reconcile_actions a LEFT JOIN torrents t ON t.id = a.torrent_id "
            "ORDER BY a.created_at DESC LIMIT 200"
        ).fetchall()
        conn.close()
        return templates.TemplateResponse(
            "actions.html",
            {
                "request": request,
                "active": "actions",
                "rows": rows,
                "auto_refresh": cfg.server.auto_refresh_seconds,
            },
        )

    return app
