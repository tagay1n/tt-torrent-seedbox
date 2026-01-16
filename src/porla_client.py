import base64
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urljoin

import requests

from config import PorlaConfig
from util import setup_logging

logger = setup_logging()


@dataclass
class PorlaTorrent:
    """Normalized Porla torrent data for internal use."""

    id: str
    name: str
    state: str
    infohash: str | None
    size_bytes: int | None
    tags: list[str] = field(default_factory=list)


@dataclass
class TrackerStat:
    """Tracker scrape stats for a single tracker endpoint."""

    tracker_url: str
    scrape_complete: int | None
    scrape_incomplete: int | None
    scrape_downloaded: int | None
    scrape_status: str


class PorlaClient:
    """JSON-RPC client wrapper for Porla API."""

    def __init__(self, config: PorlaConfig, session: requests.Session) -> None:
        self.config = config
        self.session = session

    def _headers(self) -> dict[str, str]:
        if self.config.token:
            return {"Authorization": f"Bearer {self.config.token}"}
        return {}

    def _url(self, path: str) -> str:
        return urljoin(self.config.base_url.rstrip("/") + "/", path.lstrip("/"))

    def health(self) -> bool:
        result = self._rpc_call("sys.versions", {})
        return result is not None

    def add_torrent(
        self,
        title,
        torrent_url: str | None,
    ) -> PorlaTorrent | None:
        params: dict[str, Any] = {}
        if self.config.add_save_path:
            params.setdefault("save_path", self.config.add_save_path)
        torrent_bytes = self._fetch_torrent_bytes(torrent_url)
        params["ti"] = base64.b64encode(torrent_bytes).decode("ascii")
        params["name"] = title

        result = self._rpc_call("torrents.add", params)
        if error := result.get("error"):
            if error["code"] == -3:
                logger.warning("Torrent already in porla session")
                return None
            raise ValueError(f"Got error on adding torrent: {error}")
        return next(i for i in result["result"]["info_hash"] if i)

    def list_torrents(self, tag: str) -> list[PorlaTorrent]:
        result = self._rpc_call("torrents.list", {})
        items = _rpc_items(result)
        torrents = [self._to_torrent(item) for item in items if item]
        if tag:
            return [t for t in torrents if tag in t.tags]
        return torrents

    def get_torrent(self, torrent_id: str) -> PorlaTorrent | None:
        result = self._rpc_call("torrents.list", {})
        items = _rpc_items(result)
        for item in items:
            torrent = self._to_torrent(item)
            if torrent.id == torrent_id or (torrent.infohash and torrent.infohash == torrent_id):
                return torrent
        return None

    def get_trackers(self, torrent_id: str) -> list[TrackerStat]:
        result = self._rpc_call("torrents.trackers.list", {"info_hash": torrent_id})
        trackers = _rpc_items(result)
        stats: list[TrackerStat] = []
        for tracker in trackers:
            stats.append(
                TrackerStat(
                    tracker_url=str(tracker.get("url") or tracker.get("trackerUrl") or ""),
                    scrape_complete=_first_int(
                        tracker, ["scrape_complete", "scrapeComplete", "complete"]
                    ),
                    scrape_incomplete=_first_int(
                        tracker, ["scrape_incomplete", "scrapeIncomplete", "incomplete"]
                    ),
                    scrape_downloaded=_first_int(
                        tracker, ["scrape_downloaded", "scrapeDownloaded", "downloaded"]
                    ),
                    scrape_status=str(
                        tracker.get("scrape_status")
                        or tracker.get("scrapeStatus")
                        or tracker.get("status")
                        or "ok"
                    ),
                )
            )
        return stats

    def remove_torrent(self, torrent_id: str, delete_data: bool) -> bool:
        params = {"info_hash": torrent_id, "delete_data": delete_data}
        result = self._rpc_call("torrents.remove", params)
        return result is not None

    def _to_torrent(self, data: dict[str, Any]) -> PorlaTorrent:
        tags_value = _first(data, ["tags", "tag", "labels"])
        tags: list[str] = []
        if isinstance(tags_value, list):
            tags = [str(x) for x in tags_value if x]
        elif isinstance(tags_value, str):
            tags = [tags_value]
        return PorlaTorrent(
            id=str(_first(data, ["id", "torrentId", "hash", "infoHash"]) or ""),
            name=str(_first(data, ["name", "title"]) or ""),
            state=str(_first(data, ["state", "status"]) or ""),
            infohash=_first(data, ["infoHash", "hash"]),
            size_bytes=_first_int(data, ["size", "sizeBytes"]),
            tags=tags,
        )

    def _rpc_call(self, method: str, params: dict[str, Any]) -> Any | None:
        url = self._url(self.config.jsonrpc_url)
        payload = {"jsonrpc": "2.0", "method": method, "params": params}
        resp = self.session.post(
            url,
            json=payload,
            headers={**self._headers(), "Content-Type": "application/json"},
            timeout=20,
        )
        resp.raise_for_status()
        # resp =
        # if error := resp.get("error"):
        #     raise ValueError(f"Got error on calling method '{method}': {error}")

        return resp.json()

    def _fetch_torrent_bytes(self, torrent_url: str) -> bytes | None:
        resp = self.session.get(torrent_url, timeout=20)
        resp.raise_for_status()
        return resp.content


def _first(data: dict[str, Any], keys: Iterable[str]) -> Any:
    for key in keys:
        if key in data and data[key] is not None:
            return data[key]
    return None


def _first_int(data: dict[str, Any], keys: Iterable[str]) -> int | None:
    value = _first(data, keys)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _rpc_items(result: Any) -> list[dict[str, Any]]:
    if result is None:
        return []
    if isinstance(result, list):
        return [item for item in result if isinstance(item, dict)]
    if isinstance(result, dict):
        for key in ("items", "torrents", "trackers"):
            items = result.get(key)
            if isinstance(items, list):
                return [item for item in items if isinstance(item, dict)]
    return []
