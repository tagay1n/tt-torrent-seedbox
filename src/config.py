from dataclasses import dataclass
from typing import Any

import yaml


def _get(d: dict[str, Any], key: str, default: Any) -> Any:
    if key not in d or d[key] is None:
        return default
    return d[key]


@dataclass
class TrackerConfig:
    base_url: str
    feed_url: str
    login_url: str = ""
    login_username: str = ""
    login_password: str = ""
    login_cookie_prefix: str = "phpbb"


@dataclass
class PorlaConfig:
    base_url: str
    token: str
    retry_count: int = 3
    jsonrpc_url: str = "/api/v1/jsonrpc"
    add_save_path: str = ""


@dataclass
class StorageConfig:
    db_path: str = "data/state.db"


@dataclass
class Config:
    tracker: TrackerConfig
    porla: PorlaConfig
    storage: StorageConfig


def load_config(path: str) -> Config:
    with open(path, encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}

    tracker_raw = raw.get("tracker", {})
    porla_raw = raw.get("porla", {})
    storage_raw = raw.get("storage", {})

    tracker = TrackerConfig(
        base_url=_get(tracker_raw, "base_url", ""),
        feed_url=_get(tracker_raw, "feed_url", ""),
        login_url=_get(tracker_raw, "login_url", ""),
        login_username=_get(tracker_raw, "login_username", ""),
        login_password=_get(tracker_raw, "login_password", ""),
        login_cookie_prefix=_get(tracker_raw, "login_cookie_prefix", "phpbb"),
    )

    porla = PorlaConfig(
        base_url=_get(porla_raw, "base_url", ""),
        token=_get(porla_raw, "token", ""),
        retry_count=int(_get(porla_raw, "retry_count", 3)),
        jsonrpc_url=_get(porla_raw, "jsonrpc_url", "/api/v1/jsonrpc"),
        add_save_path=_get(porla_raw, "add_save_path", ""),
    )

    storage = StorageConfig(db_path=_get(storage_raw, "db_path", "data/state.db"))

    return Config(
        tracker=tracker,
        porla=porla,
        storage=storage,
    )
