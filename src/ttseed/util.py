from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Iterable, Optional
from urllib.parse import parse_qs, urlparse

SIZE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(KB|MB|GB|TB)", re.IGNORECASE)
MAGNET_RE = re.compile(r"magnet:\?xt=urn:btih:([a-fA-F0-9]{32,40})")


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_size(text: str) -> Optional[int]:
    match = SIZE_RE.search(text)
    if not match:
        return None
    value = float(match.group(1))
    unit = match.group(2).upper()
    factor = {"KB": 1024, "MB": 1024**2, "GB": 1024**3, "TB": 1024**4}.get(unit)
    if not factor:
        return None
    return int(value * factor)


def extract_infohash(magnet_url: str) -> Optional[str]:
    match = MAGNET_RE.search(magnet_url)
    if not match:
        return None
    return match.group(1)


def parse_forum_id(url: str) -> Optional[str]:
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    forum = qs.get("f")
    if forum:
        return str(forum[0])
    return None


def load_pinned_list(path: str) -> set[str]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return {line.strip() for line in handle if line.strip() and not line.startswith("#")}
    except FileNotFoundError:
        return set()


def any_regex_match(patterns: Iterable[str], text: str) -> bool:
    for pattern in patterns:
        try:
            if re.search(pattern, text, re.IGNORECASE):
                return True
        except re.error:
            continue
    return False
