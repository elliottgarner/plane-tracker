"""Entry point:  python run.py [--demo] [--port 5000]"""
import argparse
import os
import sys

import uvicorn


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=5000)
    ap.add_argument("--demo", action="store_true", help="synthetic traffic (sets data_source=demo)")
    args = ap.parse_args()

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    if args.demo:
        from app.config import cfg
        cfg._data["data_source"] = "demo"   # in-memory only; not written to config.json
    uvicorn.run("app.main:app", host=args.host, port=args.port, log_level="info", access_log=False)


if __name__ == "__main__":
    main()
