"""Minimal polite read-only Jenkins JSON client (Basic auth, retry/backoff)."""

import base64
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

MIN_INTERVAL = 0.3
MAX_ATTEMPTS = 5


def quote(path: str) -> str:
    return urllib.parse.quote(path, safe="/:?&=,[]{}.*'")


class Jenkins:
    def __init__(self, base_url: str, user_env: str, token_env: str):
        user, token = os.environ.get(user_env), os.environ.get(token_env)
        if not (user and token):
            raise RuntimeError(f"set {user_env} and {token_env}")
        self.base = base_url.rstrip("/")
        self._auth = "Basic " + base64.b64encode(f"{user}:{token}".encode()).decode()
        self._last = 0.0

    def json(self, path: str) -> dict | None:
        """GET a JSON API path; None on 404."""
        url = self.base + quote(path)
        for attempt in range(MAX_ATTEMPTS):
            wait = MIN_INTERVAL - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            req = urllib.request.Request(url, headers={"Authorization": self._auth})
            try:
                with urllib.request.urlopen(req, timeout=120) as resp:
                    return json.load(resp)
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    return None
                if e.code in (429, 500, 502, 503, 504) and attempt < MAX_ATTEMPTS - 1:
                    time.sleep(int(e.headers.get("Retry-After") or 0) or 5 * 2**attempt)
                    continue
                raise
            except (urllib.error.URLError, TimeoutError, ConnectionError):
                if attempt == MAX_ATTEMPTS - 1:
                    raise
                time.sleep(5 * 2**attempt)
        return None
