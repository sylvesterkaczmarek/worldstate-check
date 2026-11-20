"""Verify the pinned pilot files and optionally an independently recomputed result."""

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def verify(results=None, *, decisions_only=False):
    manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    for name, expected in manifest["sha256"].items():
        if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != expected:
            raise ValueError(f"archive digest differs for {name}")
    if results is not None:
        expected = json.loads((ROOT / "results.json").read_text(encoding="utf-8"))
        actual = json.loads(results.read_text(encoding="utf-8"))
        if decisions_only:
            # Physics libraries may emit slightly different intermediate coordinates.
            actual.pop("dataset_sha256")
            expected.pop("dataset_sha256")
        if actual != expected:
            raise ValueError("recomputed results differ")
    print("Pilot v1 archive verified")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("results", nargs="?", type=Path)
    parser.add_argument("--decisions-only", action="store_true")
    args = parser.parse_args()
    verify(args.results, decisions_only=args.decisions_only)
