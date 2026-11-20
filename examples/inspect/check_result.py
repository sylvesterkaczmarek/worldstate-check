"""Check the verdicts recorded by the runnable Inspect example."""

import sys
from pathlib import Path

from inspect_ai.log import read_eval_log


def check(directory):
    files = list(directory.glob("*.eval"))
    if len(files) != 1:
        raise ValueError("expected one Inspect log")
    log = read_eval_log(files[0])
    expected = {
        "placed": "VERIFIED",
        "slipped": "NOT_VERIFIED",
        "incomplete": "UNCERTAIN",
    }
    actual = {
        sample.id: sample.scores["worldstate_scorer"].answer for sample in log.samples
    }
    if (
        log.status != "success"
        or len(log.samples) != len(expected)
        or actual != expected
    ):
        raise ValueError("Inspect example produced unexpected results")
    print(actual)


if __name__ == "__main__":
    check(Path(sys.argv[1]))
