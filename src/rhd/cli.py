import argparse
import sys
import time
import tomllib

from .collectors import build_collectors
from .render import render
from .store import open_store


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
        store.write(ts, observations)
        print(f"{collector.name}: wrote {len(observations)} observations")
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
