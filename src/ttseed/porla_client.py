from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urlencode, urljoin

import requests

from ttseed.config import PorlaConfig


@dataclass
class PorlaTorrent:
    id: str
    name: str
    state: str
    infohash: Optional[str]
    size_bytes: Optional[int]


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

    def _headers(self) -> Dict[str, str]:
        auth = self.config.auth
        if auth.type == "token" and auth.token:
            return {"Authorization": f"Bearer {auth.token}"}
        if auth.type == "basic" and auth.username:
            return {}
        return {}

    def _auth(self) -> Optional[tuple[str, str]]:
        auth = self.config.auth
        if auth.type == "basic" and auth.username:
            return (auth.username, auth.password)
        return None

    def _url(self, path: str) -> str:
        return urljoin(self.config.base_url.rstrip("/") + "/", path.lstrip("/"))

    def health(self) -> bool:
        url = self._url(self.config.endpoints["health"])
        resp = self.session.get(url, headers=self._headers(), auth=self._auth(), timeout=10)
        return bool(resp.ok)

    def add_torrent(
        self,
        magnet_url: Optional[str],
        torrent_url: Optional[str],
        tag: str,
    ) -> Optional[PorlaTorrent]:
        url = self._url(self.config.endpoints["torrents"])
        payload: Dict[str, Any] = {"tags": [tag]}
        if magnet_url:
            payload["magnetUrl"] = magnet_url
        if torrent_url:
            payload["torrentUrl"] = torrent_url
        resp = self.session.post(
            url,
            json=payload,
            headers=self._headers(),
            auth=self._auth(),
            timeout=self.config.request_timeout_seconds,
        )
        if not resp.ok:
            return None
        data = resp.json()
        return self._to_torrent(data)

    def list_torrents(self, tag: str) -> List[PorlaTorrent]:
        torrents: List[PorlaTorrent] = []
        page = 1
        while True:
            params = {"tag": tag, "page": page, "pageSize": self.config.page_size}
            url = self._url(self.config.endpoints["torrents"]) + "?" + urlencode(params)
            resp = self.session.get(
                url,
                headers=self._headers(),
                auth=self._auth(),
                timeout=self.config.request_timeout_seconds,
            )
            if not resp.ok:
                break
            data = resp.json()
            items = data.get("items", data if isinstance(data, list) else [])
            batch = [self._to_torrent(item) for item in items if item]
            torrents.extend(batch)
            if isinstance(data, dict) and data.get("page"):
                if data.get("page") >= data.get("pageCount", 1):
                    break
            if len(batch) < self.config.page_size:
                break
            page += 1
        return torrents

    def get_torrent(self, torrent_id: str) -> Optional[PorlaTorrent]:
        url = self._url(f"{self.config.endpoints['torrents'].rstrip('/')}/{torrent_id}")
        resp = self.session.get(
            url,
            headers=self._headers(),
            auth=self._auth(),
            timeout=self.config.request_timeout_seconds,
        )
        if not resp.ok:
            return None
        return self._to_torrent(resp.json())

    def get_trackers(self, torrent_id: str) -> List[TrackerStat]:
        url = self._url(self.config.endpoints["trackers"].format(id=torrent_id))
        resp = self.session.get(
            url,
            headers=self._headers(),
            auth=self._auth(),
            timeout=self.config.request_timeout_seconds,
        )
        if not resp.ok:
            return []
        data = resp.json()
        trackers = data.get("items", data if isinstance(data, list) else [])
        stats: List[TrackerStat] = []
        for tracker in trackers:
            stats.append(
                TrackerStat(
                    tracker_url=str(tracker.get("url") or tracker.get("trackerUrl") or ""),
                    scrape_complete=_first_int(tracker, ["scrapeComplete", "complete"]),
                    scrape_incomplete=_first_int(tracker, ["scrapeIncomplete", "incomplete"]),
                    scrape_downloaded=_first_int(tracker, ["scrapeDownloaded", "downloaded"]),
                    scrape_status=str(tracker.get("scrapeStatus") or tracker.get("status") or "ok"),
                )
            )
        return stats

    def remove_torrent(self, torrent_id: str, delete_data: bool) -> bool:
        params = {"deleteData": "true" if delete_data else "false"}
        url = self._url(f"{self.config.endpoints['torrents'].rstrip('/')}/{torrent_id}")
        resp = self.session.delete(
            url + "?" + urlencode(params),
            headers=self._headers(),
            auth=self._auth(),
            timeout=self.config.request_timeout_seconds,
        )
        return bool(resp.ok)

    def _to_torrent(self, data: Dict[str, Any]) -> PorlaTorrent:
        return PorlaTorrent(
            id=str(_first(data, ["id", "torrentId", "hash", "infoHash"]) or ""),
            name=str(_first(data, ["name", "title"]) or ""),
            state=str(_first(data, ["state", "status"]) or ""),
            infohash=_first(data, ["infoHash", "hash"]),
            size_bytes=_first_int(data, ["size", "sizeBytes"]),
        )


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
