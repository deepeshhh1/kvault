"""`python -m kvault` — start the server from the command line."""

import argparse

from .server import serve


def main():
    parser = argparse.ArgumentParser(
        prog="kvault",
        description="KVault — a Redis-compatible in-memory data store in pure Python.")
    parser.add_argument("--host", default="127.0.0.1", help="bind address (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=6379, help="port (default: 6379)")
    parser.add_argument("--dir", default="data", help="data directory for snapshots/AOF")
    parser.add_argument("--no-aof", action="store_true", help="disable the append-only file")
    args = parser.parse_args()
    serve(host=args.host, port=args.port, data_dir=args.dir, aof=not args.no_aof)


if __name__ == "__main__":
    main()
