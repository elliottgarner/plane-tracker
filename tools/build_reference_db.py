#!/usr/bin/env python3
"""Populate data/reference.db from open datasets.

  python tools/build_reference_db.py                      # everything
  python tools/build_reference_db.py --only aircraft airports

The service also runs this automatically in the background on first start if the DB is empty.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from app import refbuild, refdb  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="+", choices=refbuild.STEPS)
    args = ap.parse_args()
    print("Writing", refdb.REF_PATH)
    refbuild.build(args.only)
    print("Done. Restart the service to pick up changes: sudo systemctl restart plane-tracker")


if __name__ == "__main__":
    main()
