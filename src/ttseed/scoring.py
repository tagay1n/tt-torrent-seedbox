from __future__ import annotations

from datetime import datetime, timezone
from typing import Tuple


def _parse_ts(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        return None


def age_seconds(discovered_at: str | None, added_at: str | None) -> float:
    now = datetime.now(timezone.utc)
    ts = _parse_ts(discovered_at) or _parse_ts(added_at)
    if not ts:
        return 0.0
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return max((now - ts).total_seconds(), 0.0)


def vulnerability_key(
    seeders: int | None,
    leechers: int | None,
    discovered_at: str | None,
    added_at: str | None,
    size_bytes: int | None,
) -> Tuple[int, int, float, int]:
    seeders_val = seeders if seeders is not None else 9999
    leechers_val = leechers if leechers is not None else 0
    age_sec = age_seconds(discovered_at, added_at)
    size_val = size_bytes if size_bytes is not None else 10**15
    return (seeders_val, -leechers_val, -age_sec, size_val)


def compute_score(
    seeders: int | None,
    leechers: int | None,
    discovered_at: str | None,
    added_at: str | None,
    size_bytes: int | None,
) -> float:
    key = vulnerability_key(seeders, leechers, discovered_at, added_at, size_bytes)
    seeders_val, neg_leechers, neg_age, size_val = key
    leechers_val = -neg_leechers
    age_days = (-neg_age) / 86400.0 if neg_age != 0 else 0.0
    size_gb = size_val / (1024 ** 3) if size_val else 0.0
    score = 0.0
    score += max(0, 50 - min(seeders_val, 50)) * 10.0
    score += min(leechers_val, 500) * 2.0
    score += min(age_days, 3650) * 0.1
    score -= size_gb * 0.2
    return round(score, 3)
