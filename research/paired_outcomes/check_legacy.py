"""Run this optional control in an environment with worldstate-check 0.2.0."""

import json
from importlib.metadata import version
from pathlib import Path
from tempfile import TemporaryDirectory

from worldstate_check import verify_spec_data
from analyze import ROOT, SNAPSHOT_SPEC, VIEWS, visible


def main():
    if version("worldstate-check") != "0.2.0":
        raise ValueError("this historical baseline requires exactly version 0.2.0")
    results = json.loads((ROOT / "results.json").read_text(encoding="utf-8"))["records"]
    expected = {
        (r["id"], r["view"]): r["verdict"]
        for r in results
        if r["method"] == "snapshot_v02"
    }
    episodes = json.loads((ROOT / "episodes.json").read_text(encoding="utf-8"))[
        "episodes"
    ]
    count = 0
    with TemporaryDirectory() as directory:
        path = Path(directory) / "reading.json"
        for episode in episodes:
            for view in VIEWS:
                path.write_text(json.dumps(visible(episode, view)), encoding="utf-8")
                actual = verify_spec_data(SNAPSHOT_SPEC, root=directory).verdict.value
                if actual != expected[episode["id"], view]:
                    raise ValueError(
                        f"historical baseline mismatch for {episode['id']} / {view}"
                    )
                count += 1
    print(f"Matched {count} snapshot decisions with worldstate-check 0.2.0")


if __name__ == "__main__":
    main()
