import time
from dataclasses import dataclass
from urllib.parse import urljoin
from urllib.robotparser import RobotFileParser

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


@dataclass
class RateLimiter:
    """Enforces a minimum interval between outbound requests."""

    min_interval: float
    _last: float = 0.0

    def wait(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self._last = time.monotonic()


# class RobotsChecker:
#     """Fetches and caches robots.txt to answer can_fetch/crawl_delay questions."""

#     def __init__(self, base_url: str, session: requests.Session, user_agent: str) -> None:
#         self.base_url = base_url
#         self.session = session
#         self.user_agent = user_agent
#         self._parser: RobotFileParser | None = None

#     def _load(self) -> RobotFileParser:
#         if self._parser is not None:
#             return self._parser
#         robots_url = urljoin(self.base_url, "/robots.txt")
#         parser = RobotFileParser()
#         resp = self.session.get(robots_url, timeout=10)
#         resp.raise_for_status()
#         parser.parse(resp.text.splitlines())
#         self._parser = parser
#         print(self._parser)
#         return parser

#     def allowed(self, url: str) -> bool:
#         parser = self._load()
#         return parser.can_fetch(self.user_agent, url)

#     def crawl_delay(self) -> float | None:
#         parser = self._load()
#         delay = parser.crawl_delay(None)
#         if delay is None:
#             return None
#         try:
#             return float(delay)
#         except (TypeError, ValueError):
#             return None


def build_session(retry_count: int) -> requests.Session:
    retry = Retry(
        total=retry_count,
        backoff_factor=0.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST", "DELETE"],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session = requests.Session()
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session
