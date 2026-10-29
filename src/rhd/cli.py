import argparse
import sys
import time
import tomllib

from .collectors import build_collectors
from .models import Build
from .render import render
from .store import open_store


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


def collect(config: str, db: str) -> int:
    with open(config, "rb") as f:
        entries = tomllib.load(f).get("collectors", [])
    store = open_store(db)
    ts = int(time.time())
    failed = 0
    # One broken source must not stop the others from being recorded.
    for collector in build_collectors(entries):
        try:
            observations = collector.collect()
        except Exception as e:
            print(f"{collector.name}: FAILED: {e}", file=sys.stderr)
            failed += 1
            continue
        records = unchanged_filtered(store, observations)
        store.write(ts, records)
        print(f"{collector.name}: fetched {len(observations)}, wrote {len(records)}")
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="rhd")
    p.add_argument("--db", default="rhd.db", help="local SQLite path (used when D1 env vars are unset)")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect")
    c.add_argument("--config", default="config.toml")
    r = sub.add_parser("render")
    r.add_argument("--out", default="site")
    args = p.parse_args(argv)

    if args.cmd == "collect":
        return collect(args.config, args.db)
    print(render(open_store(args.db), args.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
