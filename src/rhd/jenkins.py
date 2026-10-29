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
        text = self.text(path)
        return None if text is None else json.loads(text)

    def text(self, path: str, method: str = "GET") -> str | None:
        """GET a path as text; None on 404."""
        return self._fetch(path, method)[1]

    def head(self, path: str) -> dict[str, str] | None:
        """Response headers (lowercased) from a HEAD request, without downloading a body."""
        return self._fetch(path, "HEAD")[0]

    def console_tail(self, job: str, number: int, nbytes: int = 40000) -> str | None:
        """The last nbytes of a build's console. Consoles run to tens of MB, so the size comes from a
        header-only request first; if it is unavailable, give up rather than download the whole log."""
        base = f"/job/{job}/{number}/logText/progressiveText"
        size = (self.head(f"{base}?start=0") or {}).get("x-text-size", "")
        if not size.isdigit():
            return None, None
        return self.text(f"{base}?start={max(0, int(size) - nbytes)}")

    def _fetch(self, path: str, method: str = "GET") -> tuple[dict[str, str] | None, str | None]:
        url = self.base + quote(path)
        for attempt in range(MAX_ATTEMPTS):
            wait = MIN_INTERVAL - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            req = urllib.request.Request(url, headers={"Authorization": self._auth}, method=method)
            try:
                with urllib.request.urlopen(req, timeout=120) as resp:
                    headers = {k.lower(): v for k, v in resp.headers.items()}
                    return headers, (None if method == "HEAD" else resp.read().decode("utf-8", "replace"))
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    return None, None
                if e.code in (429, 500, 502, 503, 504) and attempt < MAX_ATTEMPTS - 1:
                    time.sleep(int(e.headers.get("Retry-After") or 0) or 5 * 2**attempt)
                    continue
                raise
            except (urllib.error.URLError, TimeoutError, ConnectionError):
                if attempt == MAX_ATTEMPTS - 1:
                    raise
                time.sleep(5 * 2**attempt)
        return None, None
