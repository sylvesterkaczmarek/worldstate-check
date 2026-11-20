"""Recompute view-matched pilot comparisons offline. No model or simulator required."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import statistics
import time
from collections import Counter
from pathlib import Path
from tempfile import TemporaryDirectory

from worldstate_check import verify_spec_data
from oracle import label

ROOT = Path(__file__).resolve().parent
VIEWS = ("ack", "snapshot", "bound", "window")
PASS, FAIL, UNKNOWN = "VERIFIED", "NOT_VERIFIED", "UNCERTAIN"


def visible(episode, view):
    result = {"ack": episode["ack"], "samples": []}
    if view == "ack":
        return result
    rows = episode["samples"] if view == "window" else episode["samples"][:1]
    for row in rows:
        result["samples"].append(
            {k: v for k, v in row.items() if k != "subject" or view != "snapshot"}
        )
    if view in {"bound", "window"}:
        result["before"] = episode["before"]
    return result


def contract(transition=False):
    checks = [
        {
            "id": "stable",
            "type": "window",
            "path": "reading.json",
            "series": "samples",
            "timestamp_field": "t",
            "sample_id_field": "id",
            "start": 0,
            "end": 1,
            "max_gap_seconds": 0.5,
            "match": {"subject": "current"},
            "field": "good",
            "operator": "eq",
            "value": True,
        }
    ]
    if transition:
        checks.append(
            {
                "id": "new",
                "type": "json",
                "path": "reading.json",
                "field": "before",
                "operator": "eq",
                "value": False,
            }
        )
    return {"version": 1, "task": "verify-outcome", "checks": checks}


SNAPSHOT_SPEC = {
    "version": 1,
    "task": "single-snapshot",
    "checks": [
        {
            "id": "initial",
            "type": "metric",
            "source": {
                "type": "json",
                "path": "reading.json",
                "field": "samples.0.good",
            },
            "operator": "eq",
            "value": True,
        }
    ],
}


def manual(view, transition, temporal):
    if transition and view.get("before") is True:
        return FAIL
    eligible = [row for row in view["samples"] if row.get("subject") == "current"]
    if not eligible:
        return UNKNOWN
    selected = eligible if temporal else eligible[-1:]
    if any(row["good"] is False for row in selected):
        return FAIL
    if transition and "before" not in view:
        return UNKNOWN
    if temporal:
        # Independently expressed for the pilot's three prescribed acquisition times.
        if [row["t"] for row in eligible] != [0, 0.5, 1] or len(
            {r["id"] for r in eligible}
        ) != 3:
            return UNKNOWN
    return PASS


def summarize(rows):
    counts = Counter((row["truth"], row["verdict"]) for row in rows)

    def rate(key, truth):
        total = sum(counts[truth, k] for k in (PASS, FAIL, UNKNOWN))
        return counts[truth, key] / total if total else None

    return {
        "episodes": len(rows),
        "confusion": {
            str(truth).lower(): {v: counts[truth, v] for v in (PASS, FAIL, UNKNOWN)}
            for truth in (False, True)
        },
        "false_verification": rate(PASS, False),
        "true_acceptance": rate(PASS, True),
        "true_rejection": rate(FAIL, True),
        "abstain_failure": rate(UNKNOWN, False),
        "abstain_success": rate(UNKNOWN, True),
        "coverage": sum(row["verdict"] != UNKNOWN for row in rows) / len(rows),
        "mean_available_samples": statistics.mean(row["samples"] for row in rows),
    }


def paired_interval(rows, metric):
    groups = {}
    for row in rows:
        groups.setdefault(row["family"], {}).setdefault(row["method"], []).append(row)

    def delta(selection):
        def values(method):
            return summarize(
                [r for family in selection for r in groups[family][method]]
            )[metric]

        return values("worldstate") - values("snapshot_v02")

    labels = sorted(groups)
    rng = random.Random(20261120)
    estimates = sorted(delta(rng.choices(labels, k=len(labels))) for _ in range(1000))
    return {
        "difference": delta(labels),
        "interval95": [estimates[24], estimates[974]],
        "families": len(labels),
    }


def analyze(dataset):
    records = []
    elapsed = {}
    with TemporaryDirectory() as directory:
        root = Path(directory)
        for episode in dataset["episodes"]:
            truth = label(episode)
            for view_name in VIEWS:
                view = visible(episode, view_name)
                (root / "reading.json").write_text(json.dumps(view), encoding="utf-8")
                transition = episode["requires_transition"]
                spec = contract(transition)
                methods = {
                    "ack": lambda: PASS if view["ack"] else FAIL,
                    "snapshot_v02": lambda: (
                        verify_spec_data(SNAPSHOT_SPEC, root=root).verdict.value
                    ),
                    "bound_latest": lambda: manual(view, transition, False),
                    "hand_timed": lambda: manual(view, transition, True),
                    "worldstate": lambda: (
                        verify_spec_data(spec, root=root).verdict.value
                    ),
                }
                for method, evaluate in methods.items():
                    start = time.perf_counter_ns()
                    verdict = evaluate()
                    timing_group = "/".join((episode["split"], episode["domain"], view_name, method))
                    elapsed.setdefault(timing_group, []).append(
                        (time.perf_counter_ns() - start) / 1e6
                    )
                    records.append(
                        {
                            "id": episode["id"],
                            "domain": episode["domain"],
                            "family": episode["family"],
                            "split": episode["split"],
                            "view": view_name,
                            "method": method,
                            "truth": truth,
                            "verdict": verdict,
                            "samples": len(view["samples"]),
                        }
                    )
    groups = {}
    for row in records:
        key = "/".join(row[k] for k in ("split", "domain", "view", "method"))
        groups.setdefault(key, []).append(row)
    paired = {}
    for domain in ("deployment", "placement"):
        rows = [
            r
            for r in records
            if r["domain"] == domain
            and r["split"] == "heldout"
            and r["view"] == "window"
        ]
        paired[domain] = {
            k: paired_interval(rows, k)
            for k in ("false_verification", "true_acceptance")
        }
    return {
        "results": {key: summarize(rows) for key, rows in groups.items()},
        "paired_heldout": paired,
        "records": records,
    }, {
        method: {"median_ms": statistics.median(values), "calls": len(values)}
        for method, values in elapsed.items()
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, default=ROOT / "episodes.json")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--timings", type=Path)
    args = parser.parse_args()
    raw = args.data.read_bytes()
    results, elapsed = analyze(json.loads(raw))
    results["dataset_sha256"] = hashlib.sha256(raw).hexdigest()
    if args.out:
        args.out.write_text(
            json.dumps(results, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
    if args.timings:
        args.timings.write_text(json.dumps(elapsed, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(results["paired_heldout"], indent=2))
