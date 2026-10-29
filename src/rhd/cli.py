import argparse
import sys
import time
import tomllib

from .collectors import build_collectors
from .failures import reconcile
from .models import Build, FailureSnapshot
from .store import statements
from .alerts import Thresholds, evaluate
from .render import render
from .store import open_store


RETENTION_DAYS = 45   # builds and their test failures
HISTORY_DAYS = 120    # observations and resolved package failures


def prune(store, ts: int) -> None:
    recent, old = ts - RETENTION_DAYS * 86400, ts - HISTORY_DAYS * 86400
    store.execute([
        ("DELETE FROM build WHERE ts < ?", [recent]),
        ("DELETE FROM test_failure WHERE ts < ?", [recent]),
        ("DELETE FROM test_fetch WHERE ts < ?", [recent]),
        ("DELETE FROM observation WHERE ts < ?", [old]),
        ("DELETE FROM pkg_failure WHERE resolved IS NOT NULL AND resolved < ?", [old]),
    ])


def load_config(path: str) -> dict:
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except FileNotFoundError:
        return {}


def unchanged_filtered(store, records):
    """Drop builds already stored in the same state; finished builds never change,
    so steady-state runs only write new or just-finished builds."""
    builds = [r for r in records if isinstance(r, Build)]
    if not builds:
        return records
    oldest = min(b.ts for b in builds)
    stored = {
        (r["server"], r["job"], r["number"]):
            (r["result"], r["duration_s"], r["fail"], r["skip"], r["total"])
        for r in store.query(
            "SELECT server, job, number, result, duration_s, fail, skip, total "
            "FROM build WHERE ts >= ?", [oldest])
    }
    return [r for r in records if not (isinstance(r, Build) and stored.get(r.key) == r.state)]


def collect(config: str, db: str, only: list[str] | None = None) -> int:
    entries = load_config(config).get("collectors", [])
    if only:
        entries = [e for e in entries if e["type"] in only]
        if not entries:
            raise SystemExit(f"no configured collectors of type {only}")
    store = open_store(db)
    ts = int(time.time())
    failed = 0
    # One broken source must not stop the others from being recorded.
    for collector in build_collectors(entries):
        try:
            if hasattr(collector, "bind"):
                collector.bind(store)
            observations = collector.collect()
        except Exception as e:
            print(f"{collector.name}: FAILED: {e}", file=sys.stderr)
            failed += 1
            continue
        records = unchanged_filtered(store, observations)
        stmts = statements(ts, [r for r in records if not isinstance(r, FailureSnapshot)])
        for snap in (r for r in records if isinstance(r, FailureSnapshot)):
            stmts += reconcile(store, ts, snap)
        store.execute(stmts)
        print(f"{collector.name}: fetched {len(observations)}, wrote {len(stmts)}")
    prune(store, ts)
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="rhd")
    p.add_argument("--db", default="rhd.db", help="local SQLite path (used when D1 env vars are unset)")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect")
    c.add_argument("--config", default="config.toml")
    c.add_argument("--only", help="comma-separated collector types to run (e.g. github_repo,rosdistro)")
    r = sub.add_parser("render")
    r.add_argument("--out", default="site")
    r.add_argument("--config", default="config.toml")
    a = sub.add_parser("alerts", help="print firing alerts; exit 2 if any are 'bad'")
    a.add_argument("--config", default="config.toml")
    args = p.parse_args(argv)

    if args.cmd == "collect":
        return collect(args.config, args.db, args.only.split(",") if args.only else None)
    thresholds = Thresholds.from_config(load_config(args.config).get("alerts"))
    store = open_store(args.db)
    if args.cmd == "alerts":
        found = evaluate(store, time.time(), thresholds)
        for a in found:
            print(f"[{a.severity}] {a.tab}: {a.title}" + (f" ({a.detail})" if a.detail else ""))
        print(f"{len(found)} alert(s)")
        return 2 if any(a.severity == "bad" for a in found) else 0
    print(render(store, args.out, thresholds))
    return 0


if __name__ == "__main__":
    sys.exit(main())
