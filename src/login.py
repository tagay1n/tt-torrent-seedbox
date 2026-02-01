"""Helper for logging into phpBB and persisting cookies in a session."""

import re

from config import Config
from util import setup_logging

logger = setup_logging()

INPUT_RE = re.compile(r"<input[^>]+>", re.IGNORECASE)
NAME_RE = re.compile(r"name=[\"']?([^\"'\s>]+)", re.IGNORECASE)
VALUE_RE = re.compile(r"value=[\"']?([^\"'>]*)", re.IGNORECASE)


def _build_login_payload(
    html: str, username: str, password: str, extra: dict[str, str]
) -> dict[str, str]:
    payload: dict[str, str] = {}
    for input_tag in INPUT_RE.findall(html):
        name_match = NAME_RE.search(input_tag)
        if not name_match:
            continue
        name = name_match.group(1)
        value_match = VALUE_RE.search(input_tag)
        value = value_match.group(1) if value_match else ""
        payload[name] = value

    payload["username"] = username
    payload["password"] = password
    for key, value in extra.items():
        payload[key] = value
    return payload


def login(config: Config, session) -> bool:
    if not (username := config.tracker.login_username) or not (
        password := config.tracker.login_password
    ):
        raise ValueError("Username/password missing")

    if not (login_url := config.tracker.login_url):
        raise ValueError("Login url missing")

    resp = session.get(login_url, timeout=20)
    if not resp.ok:
        raise ValueError("Login page fetch failed status=%s", resp.status_code)

    payload = _build_login_payload(resp.text, username, password, {"autologin": "on"})
    post = session.post(login_url, data=payload, timeout=20)
    if not post.ok:
        logger.warning("Login post failed status=%s", post.status_code)

    prefix = config.tracker.login_cookie_prefix.lower()
    if prefix:
        for cookie in session.cookies:
            if cookie.name.lower().startswith(prefix):
                logger.debug("Login ok")
                return
    raise ValueError("Login may have failed (no expected cookies)")
