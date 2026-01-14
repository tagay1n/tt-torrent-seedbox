from __future__ import annotations

import base64
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urljoin

import requests

from ttseed.config import PorlaConfig


@dataclass
class PorlaTorrent:
    id: str
    name: str
    state: str
    infohash: Optional[str]
    size_bytes: Optional[int]
    tags: List[str] = field(default_factory=list)


@dataclass
class TrackerStat:
    tracker_url: str
    scrape_complete: Optional[int]
    scrape_incomplete: Optional[int]
    scrape_downloaded: Optional[int]
    scrape_status: str


class PorlaClient:
    def __init__(self, config: PorlaConfig, session: requests.Session) -> None:
        self.config = config
        self.session = session
        self.tag_mode = (config.tag_mode or "porla").lower()

    def _headers(self) -> Dict[str, str]:
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
        magnet_url: Optional[str],
        torrent_url: Optional[str],
        tag: str,
    ) -> Optional[PorlaTorrent]:
        params: Dict[str, Any] = {**self.config.add_params}
        if self.config.add_preset:
            params.setdefault("preset", self.config.add_preset)
        if self.config.add_save_path:
            params.setdefault("save_path", self.config.add_save_path)
        if magnet_url:
            params["magnet_uri"] = magnet_url
        elif torrent_url:
            torrent_bytes = self._fetch_torrent_bytes(torrent_url)
            if not torrent_bytes:
                return None
            params["ti"] = base64.b64encode(torrent_bytes).decode("ascii")
        else:
            return None
        result = self._rpc_call("torrents.add", params)
        info_hash = None
        if isinstance(result, dict):
            info_hash = _first(result, ["info_hash", "infoHash", "hash"])
            if isinstance(result.get("info_hash"), list):
                for item in result.get("info_hash"):
                    if item:
                        info_hash = item
                        break
        if not info_hash:
            return None
        return PorlaTorrent(
            id=str(info_hash),
            name="",
            state="queued",
            infohash=str(info_hash),
            size_bytes=None,
            tags=[tag] if tag else [],
        )

    def list_torrents(self, tag: str) -> List[PorlaTorrent]:
        result = self._rpc_call("torrents.list", {})
        items = _rpc_items(result)
        torrents = [self._to_torrent(item) for item in items if item]
        if tag:
            filtered = [t for t in torrents if tag in t.tags]
            if filtered:
                return filtered
            if self.tag_mode != "porla":
                return []
        return torrents

    def get_torrent(self, torrent_id: str) -> Optional[PorlaTorrent]:
        result = self._rpc_call("torrents.list", {})
        items = _rpc_items(result)
        for item in items:
            torrent = self._to_torrent(item)
            if torrent.id == torrent_id or (torrent.infohash and torrent.infohash == torrent_id):
                return torrent
        return None

    def get_trackers(self, torrent_id: str) -> List[TrackerStat]:
        result = self._rpc_call("torrents.trackers.list", {"info_hash": torrent_id})
        trackers = _rpc_items(result)
        stats: List[TrackerStat] = []
        for tracker in trackers:
            stats.append(
                TrackerStat(
                    tracker_url=str(tracker.get("url") or tracker.get("trackerUrl") or ""),
                    scrape_complete=_first_int(tracker, ["scrape_complete", "scrapeComplete", "complete"]),
                    scrape_incomplete=_first_int(tracker, ["scrape_incomplete", "scrapeIncomplete", "incomplete"]),
                    scrape_downloaded=_first_int(tracker, ["scrape_downloaded", "scrapeDownloaded", "downloaded"]),
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

    def _to_torrent(self, data: Dict[str, Any]) -> PorlaTorrent:
        tags_value = _first(data, ["tags", "tag", "labels"])
        tags: List[str] = []
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

    def _rpc_call(self, method: str, params: Dict[str, Any]) -> Optional[Any]:
        url = self._url(self.config.jsonrpc_url)
        payload = {"jsonrpc": "2.0", "method": method, "params": params, "id": 1}
        resp = self.session.post(
            url,
            json=payload,
            headers={**self._headers(), "Content-Type": "application/json"},
            timeout=self.config.request_timeout_seconds,
        )
        if not resp.ok:
            return None
        data = resp.json()
        if isinstance(data, dict) and data.get("error"):
            return None
        return data.get("result") if isinstance(data, dict) else None

    def _fetch_torrent_bytes(self, torrent_url: str) -> Optional[bytes]:
        resp = self.session.get(torrent_url, timeout=self.config.request_timeout_seconds)
        if not resp.ok:
            return None
        return resp.content


def _first(data: Dict[str, Any], keys: Iterable[str]) -> Any:
    for key in keys:
        if key in data and data[key] is not None:
            return data[key]
    return None


def _first_int(data: Dict[str, Any], keys: Iterable[str]) -> Optional[int]:
    value = _first(data, keys)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _rpc_items(result: Any) -> List[Dict[str, Any]]:
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
