import logging
import re
from collections.abc import Iterable
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

# SIZE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(KB|MB|GB|TB)", re.IGNORECASE)
# MAGNET_RE = re.compile(r"magnet:\?xt=urn:btih:([a-fA-F0-9]{32,40})")


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_size(text: str) -> int | None:
    m = re.search(r"\(([\d\s\u00A0\u202F]+)\s*байт\)", text, flags=re.IGNORECASE)
    if not m:
        raise ValueError(f"Could not parse bytes count in the string: '{text}'")

    # Remove spaces + NBSP + narrow NBSP, then parse
    digits = re.sub(r"[\s\u00A0\u202F]+", "", m.group(1))
    return int(digits)


# def extract_infohash(magnet_url: str) -> str | None:
#     # match = MAGNET_RE.search(magnet_url)
#     if not match:
#         return None
#     return match.group(1)


# def parse_forum_id(url: str) -> str | None:
#     parsed = urlparse(url)
#     qs = parse_qs(parsed.query)
#     forum = qs.get("f")
#     if forum:
#         return str(forum[0])
#     return None


# def load_pinned_list(path: str) -> set[str]:
#     try:
#         with open(path, encoding="utf-8") as handle:
#             return {line.strip() for line in handle if line.strip() and not line.startswith("#")}
#     except FileNotFoundError:
#         return set()


# def any_regex_match(patterns: Iterable[str], text: str) -> bool:
#     for pattern in patterns:
#         try:
#             if re.search(pattern, text, re.IGNORECASE):
#                 return True
#         except re.error:
#             continue
#     return False


def normalize_topic_url(url: str) -> str:
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return url
    query = parse_qs(parsed.query, keep_blank_values=True)
    if "t" not in query:
        if "sid" in query:
            query.pop("sid", None)
            new_query = urlencode({k: v for k, v in query.items()}, doseq=True)
            return urlunparse(parsed._replace(query=new_query, fragment=""))
        return urlunparse(parsed._replace(fragment=""))

    new_query = {}
    if "f" in query:
        new_query["f"] = query["f"][0]
    new_query["t"] = query["t"][0]
    return urlunparse(parsed._replace(query=urlencode(new_query), fragment=""))


def setup_logging() -> logging.Logger:
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    return logging.getLogger("ttseed")
