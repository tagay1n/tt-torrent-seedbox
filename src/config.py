from dataclasses import dataclass, field
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
    user_agent: str = "ttseed/0.1"
    rate_limit_per_sec: float = 1.0
    sitemap_url: str = ""
    sitemap_backfill_enabled: bool = False
    sitemap_backfill_force: bool = False
    sitemap_backfill_limit: int = 0
    sitemap_topic_regex: list[str] = field(default_factory=list)
    login_enabled: bool = False
    login_url: str = ""
    login_username: str = ""
    login_password: str = ""
    login_cookie_prefix: str = "phpbb"
    login_extra: dict[str, str] = field(default_factory=dict)
    allow_forums: list[str] = field(default_factory=list)
    allow_tags: list[str] = field(default_factory=list)
    allow_regex_title: list[str] = field(default_factory=list)
    html_parse_enabled: bool = False
    topic_cache_ttl_minutes: int = 720


@dataclass
class PorlaConfig:
    base_url: str
    token: str
    managed_tag: str = "tt-archive"
    request_timeout_seconds: int = 15
    retry_count: int = 3
    jsonrpc_url: str = "/api/v1/jsonrpc"
    tag_mode: str = "porla"  # porla|db
    add_preset: str = ""
    add_save_path: str = ""
    add_params: dict[str, Any] = field(default_factory=dict)


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


def load_config(path: str) -> Config:
    with open(path, encoding="utf-8") as handle:
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
        sitemap_url=_get(tracker_raw, "sitemap_url", ""),
        sitemap_backfill_enabled=bool(_get(tracker_raw, "sitemap_backfill_enabled", False)),
        sitemap_backfill_force=bool(_get(tracker_raw, "sitemap_backfill_force", False)),
        sitemap_backfill_limit=int(_get(tracker_raw, "sitemap_backfill_limit", 0)),
        sitemap_topic_regex=[str(x) for x in _get(tracker_raw, "sitemap_topic_regex", [])],
        login_enabled=bool(_get(tracker_raw, "login_enabled", False)),
        login_url=_get(tracker_raw, "login_url", ""),
        login_username=_get(tracker_raw, "login_username", ""),
        login_password=_get(tracker_raw, "login_password", ""),
        login_cookie_prefix=_get(tracker_raw, "login_cookie_prefix", "phpbb"),
        login_extra={str(k): str(v) for k, v in _get(tracker_raw, "login_extra", {}).items()},
        allow_forums=[str(x) for x in _get(tracker_raw, "allow_forums", [])],
        allow_tags=[str(x) for x in _get(tracker_raw, "allow_tags", [])],
        allow_regex_title=[str(x) for x in _get(tracker_raw, "allow_regex_title", [])],
        html_parse_enabled=bool(_get(tracker_raw, "html_parse_enabled", False)),
        topic_cache_ttl_minutes=int(_get(tracker_raw, "topic_cache_ttl_minutes", 720)),
    )

    porla = PorlaConfig(
        base_url=_get(porla_raw, "base_url", ""),
        token=_get(porla_raw, "token", ""),
        managed_tag=_get(porla_raw, "managed_tag", "tt-archive"),
        request_timeout_seconds=int(_get(porla_raw, "request_timeout_seconds", 15)),
        retry_count=int(_get(porla_raw, "retry_count", 3)),
        jsonrpc_url=_get(porla_raw, "jsonrpc_url", "/api/v1/jsonrpc"),
        tag_mode=_get(porla_raw, "tag_mode", "porla"),
        add_preset=_get(porla_raw, "add_preset", ""),
        add_save_path=_get(porla_raw, "add_save_path", ""),
        add_params={str(k): v for k, v in _get(porla_raw, "add_params", {}).items()},
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
