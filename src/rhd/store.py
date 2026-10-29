import json
import os
import sqlite3
import urllib.request
from pathlib import Path
from typing import Protocol

from .models import Observation

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "schema"

INSERT = (
    "INSERT OR REPLACE INTO observation (ts, source, metric, labels, value) "
    "VALUES (?, ?, ?, ?, ?)"
)


class Store(Protocol):
    def write(self, ts: int, observations: list[Observation]) -> None: ...
    def query(self, sql: str, params: list | None = None) -> list[dict]: ...


def _migrations() -> list[str]:
    return [p.read_text() for p in sorted(SCHEMA_DIR.glob("*.sql"))]


class SqliteStore:
    def __init__(self, path: str):
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        for sql in _migrations():
            self.db.executescript(sql)

    def write(self, ts, observations):
        self.db.executemany(
            INSERT, [(ts, o.source, o.metric, o.labels_json, o.value) for o in observations]
        )
        self.db.commit()

    def query(self, sql, params=None):
        return [dict(r) for r in self.db.execute(sql, params or [])]


class D1Store:
    """Cloudflare D1 over the REST API. Only top-line rollups belong here."""

    def __init__(self, account_id: str, database_id: str, token: str):
        self.url = (
            f"https://api.cloudflare.com/client/v4/accounts/{account_id}"
            f"/d1/database/{database_id}/query"
        )
        self.token = token
        for sql in _migrations():
            self._post(sql, [])

    def _post(self, sql: str, params: list) -> list[dict]:
        req = urllib.request.Request(
            self.url,
            data=json.dumps({"sql": sql, "params": params}).encode(),
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = json.load(resp)
        if not body.get("success"):
            raise RuntimeError(f"D1 error: {body.get('errors')}")
        return body["result"][0].get("results", [])

    def write(self, ts, observations):
        for o in observations:
            self._post(INSERT, [ts, o.source, o.metric, o.labels_json, o.value])

    def query(self, sql, params=None):
        return self._post(sql, params or [])


def open_store(db_path: str = "rhd.db") -> Store:
    """D1 when its env vars are set (CI), otherwise a local SQLite file."""
    if os.environ.get("D1_DATABASE_ID"):
        return D1Store(
            os.environ["CLOUDFLARE_ACCOUNT_ID"],
            os.environ["D1_DATABASE_ID"],
            os.environ["CLOUDFLARE_API_TOKEN"],
        )
    return SqliteStore(db_path)
