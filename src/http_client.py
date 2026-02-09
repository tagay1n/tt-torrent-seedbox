"""HTTP session factory and a simple rate limiter for outbound requests."""

import time
from dataclasses import dataclass

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


@dataclass
class RateLimiter:
    """Enforces a minimum interval between outbound requests."""

    min_interval: float
    _last: float = 0.0

    def wait(self) -> None:
        """Block until the minimum interval from the previous call has elapsed."""
        now = time.monotonic()
        elapsed = now - self._last
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self._last = time.monotonic()


def build_session(retry_count: int) -> requests.Session:
    """Build a shared HTTP session with retry policy for transient failures."""
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
