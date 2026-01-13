from __future__ import annotations

import argparse
import sys

import uvicorn

from ttseed.config import load_config
from ttseed.dashboard import create_app
from ttseed.db import connect, init_db
from ttseed.ingest import run as run_ingest
from ttseed.reconcile import run as run_reconcile
from ttseed.stats import run as run_stats


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ttseed policy engine")
    parser.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    return parser


def main_ingest() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    run_ingest(args.config)


def main_stats() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    run_stats(args.config)


def main_reconcile() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    run_reconcile(args.config)


def main_dashboard() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    cfg = load_config(args.config)
    app = create_app(args.config)
    uvicorn.run(app, host=cfg.server.host, port=cfg.server.port)


def main_initdb() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    cfg = load_config(args.config)
    conn = connect(cfg.storage.db_path)
    init_db(conn)
    conn.close()
    print("db initialized")


if __name__ == "__main__":
    sys.exit(main_ingest())
