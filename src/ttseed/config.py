from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import yaml


def _get(d: Dict[str, Any], key: str, default: Any) -> Any:
    if key not in d or d[key] is None:
        return default
    return d[key]


@dataclass
class TrackerConfig:
    base_url: str
    feed_url: str
    user_agent: str = "ttseed/0.1"
    rate_limit_per_sec: float = 1.0
    allow_forums: List[str] = field(default_factory=list)
    allow_tags: List[str] = field(default_factory=list)
    allow_regex_title: List[str] = field(default_factory=list)
    html_parse_enabled: bool = False
    topic_cache_ttl_minutes: int = 720


@dataclass
class PorlaAuth:
    type: str = "none"
    token: str = ""
    username: str = ""
    password: str = ""


@dataclass
class PorlaConfig:
    base_url: str
    auth: PorlaAuth
    managed_tag: str = "tt-archive"
    request_timeout_seconds: int = 15
    retry_count: int = 3
    page_size: int = 200
    endpoints: Dict[str, str] = field(default_factory=dict)


@dataclass
class PolicyConfig:
    max_total_bytes: int = 900_000_000_000
    max_torrents: int = 50_000
    allow_delete_data: bool = True
    pinned_list_path: str = "pinned.txt"
    never_delete_if_pinned: bool = True


@dataclass
class StorageConfig:
    db_path: str = "data/state.db"


@dataclass
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = 8080
    auto_refresh_seconds: int = 60


@dataclass
class Config:
    tracker: TrackerConfig
    porla: PorlaConfig
    policy: PolicyConfig
    storage: StorageConfig
    server: ServerConfig


DEFAULT_PORLA_ENDPOINTS = {
    "health": "/api/v1/health",
    "torrents": "/api/v1/torrents",
    "trackers": "/api/v1/torrents/{id}/trackers",
}


def load_config(path: str) -> Config:
    with open(path, "r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}

    tracker_raw = raw.get("tracker", {})
    porla_raw = raw.get("porla", {})
    policy_raw = raw.get("policy", {})
    storage_raw = raw.get("storage", {})
    server_raw = raw.get("server", {})

    tracker = TrackerConfig(
        base_url=_get(tracker_raw, "base_url", ""),
        feed_url=_get(tracker_raw, "feed_url", ""),
        user_agent=_get(tracker_raw, "user_agent", "ttseed/0.1"),
        rate_limit_per_sec=float(_get(tracker_raw, "rate_limit_per_sec", 1.0)),
        allow_forums=[str(x) for x in _get(tracker_raw, "allow_forums", [])],
        allow_tags=[str(x) for x in _get(tracker_raw, "allow_tags", [])],
        allow_regex_title=[str(x) for x in _get(tracker_raw, "allow_regex_title", [])],
        html_parse_enabled=bool(_get(tracker_raw, "html_parse_enabled", False)),
        topic_cache_ttl_minutes=int(_get(tracker_raw, "topic_cache_ttl_minutes", 720)),
    )

    auth_raw = porla_raw.get("auth", {})
    porla = PorlaConfig(
        base_url=_get(porla_raw, "base_url", ""),
        auth=PorlaAuth(
            type=_get(auth_raw, "type", "none"),
            token=_get(auth_raw, "token", ""),
            username=_get(auth_raw, "username", ""),
            password=_get(auth_raw, "password", ""),
        ),
        managed_tag=_get(porla_raw, "managed_tag", "tt-archive"),
        request_timeout_seconds=int(_get(porla_raw, "request_timeout_seconds", 15)),
        retry_count=int(_get(porla_raw, "retry_count", 3)),
        page_size=int(_get(porla_raw, "page_size", 200)),
        endpoints={**DEFAULT_PORLA_ENDPOINTS, **_get(porla_raw, "endpoints", {})},
    )

    policy = PolicyConfig(
        max_total_bytes=int(_get(policy_raw, "max_total_bytes", 900_000_000_000)),
        max_torrents=int(_get(policy_raw, "max_torrents", 50_000)),
        allow_delete_data=bool(_get(policy_raw, "allow_delete_data", True)),
        pinned_list_path=_get(policy_raw, "pinned_list_path", "pinned.txt"),
        never_delete_if_pinned=bool(_get(policy_raw, "never_delete_if_pinned", True)),
    )

    storage = StorageConfig(db_path=_get(storage_raw, "db_path", "data/state.db"))

    server = ServerConfig(
        host=_get(server_raw, "host", "127.0.0.1"),
        port=int(_get(server_raw, "port", 8080)),
        auto_refresh_seconds=int(_get(server_raw, "auto_refresh_seconds", 60)),
    )

    return Config(
        tracker=tracker,
        porla=porla,
        policy=policy,
        storage=storage,
        server=server,
    )
