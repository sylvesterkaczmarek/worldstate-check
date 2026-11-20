"""Record loopback deployments and headless MuJoCo placements for the frozen pilot."""

from __future__ import annotations

import argparse
import hashlib
import json
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread
from urllib.request import ProxyHandler, build_opener

import mujoco


ROOT = Path(__file__).resolve().parent
CASES = (
    "success",
    "slip",
    "wrong",
    "missing-success",
    "missing-failure",
    "duplicate",
    "already-allowed",
    "transition-required",
    "ordinary-failure",
    "unseen-transient",
    "transition-achieved",
)


@contextmanager
def worker(revision, requests, compute):
    class Handler(BaseHTTPRequestHandler):
        actual = 0

        def do_GET(self):
            requests.append({"worker": revision, "actual": self.actual})
            body = json.dumps({"subject": revision, "result": self.actual}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    Handler.actual = compute(3)
    with HTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = Thread(
            target=server.serve_forever, kwargs={"poll_interval": 0.005}, daemon=True
        )
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}/canary", Handler
        finally:
            server.shutdown()
            thread.join()


def deployment(family, case):
    compute = {
        "square": lambda x: x * x,
        "double": lambda x: 2 * x,
        "increment": lambda x: x + 1,
    }[family]
    expected = compute(3)
    requests, rows = [], []
    client = build_opener(ProxyHandler({}))
    with (
        worker("current", requests, compute) as (new_url, new),
        worker("previous", requests, compute) as (old_url, _),
    ):
        pre_url = (
            new_url if case in {"already-allowed", "transition-required"} else old_url
        )
        with client.open(pre_url, timeout=2) as response:
            before = json.load(response)
        pre_request = requests.pop()
        for tick in range(11):
            wrong_worker = case == "wrong" or (case == "slip" and tick >= 3)
            failed = case == "ordinary-failure" or (
                case == "missing-failure" and tick > 1
            )
            new.actual = (
                -1 if failed or (case == "unseen-transient" and tick == 3) else expected
            )
            with client.open(
                old_url if wrong_worker else new_url, timeout=2
            ) as response:
                reading = json.load(response)
            if tick in (0, 5, 10):
                rows.append(
                    {
                        "t": tick / 10,
                        "id": tick,
                        "subject": reading["subject"],
                        "good": reading["result"] == expected,
                    }
                )
    initially = pre_request["worker"] == "current" and pre_request["actual"] == expected
    return (
        rows,
        {
            "requests": requests,
            "requested": "current",
            "expected": expected,
            "initially_satisfied": initially,
            "pre_request": pre_request,
        },
        before["subject"] == "current" and before["result"] == expected,
    )


def placement(family, case):
    geom = {
        "cube": 'type="box" size=".025 .025 .025"',
        "cylinder": 'type="cylinder" size=".025 .025"',
        "sphere": 'type="sphere" size=".025"',
    }[family]
    stable = case not in {"slip", "missing-failure", "ordinary-failure"}
    height = 0.225
    offset = 0.15 if case in {"ordinary-failure", "wrong"} else 0
    other = (
        (
            '<body name="distractor" pos="0 0 .225"><freejoint/><geom '
            + geom
            + ' mass=".05"/><site name="other_marker"/></body>'
        )
        if case == "wrong"
        else ""
    )
    marker = "other_marker" if other else "marker"
    # A weld models a closed gripper until release. Afterwards only contacts support the object.
    model = mujoco.MjModel.from_xml_string(f'''<mujoco><option timestep=".005"/>
      <worldbody><geom name="ground" type="plane" size="1 1 .01"/>
      <geom name="tray" type="box" pos="{0 if stable else 0.3} 0 .19" size=".07 .07 .01"/>
      <body name="gripper" mocap="true" pos="{offset} 0 {height}">
        <geom type="box" size=".01 .01 .01" contype="0" conaffinity="0"/></body>
      <body name="object" pos="{offset} 0 {height}"><freejoint/>
        <geom name="object_geom" {geom} mass=".05"/><site name="marker"/></body>{other}</worldbody>
      <equality><weld body1="gripper" body2="object"/></equality>
      <sensor><framepos objtype="site" objname="{marker}"/></sensor></mujoco>''')
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    # The placement task starts with a held object. Record its pre-action position,
    # then prescribe the gripper's approach and let MuJoCo integrate the release.
    start_x = offset if case in {"already-allowed", "transition-required"} else 0.16
    data.mocap_pos[0, 0] = start_x
    data.qpos[0] = start_x
    mujoco.mj_forward(model, data)
    pre_position = data.qpos[:3].tolist()
    before = bool(
        abs(data.sensordata[0]) <= 0.06 and abs(data.sensordata[2] - height) <= 0.015
    )
    for n in range(160):
        data.mocap_pos[0, 0] = start_x + (offset - start_x) * min((n + 1) / 100, 1)
        mujoco.mj_step(model, data)
    mujoco.mj_forward(model, data)
    data.eq_active[0] = 0
    rows, positions = [], []
    for step in range(201):
        if step:
            data.mocap_pos[0, 2] = height + min(step * 0.005, 0.15)
            mujoco.mj_step(model, data)
            mujoco.mj_forward(model, data)
        positions.append([round(float(v), 7) for v in data.qpos[:3]])
        if step in (0, 100, 200):
            x, y, z = data.sensordata[:3]
            good = bool(x * x + y * y <= 0.06**2 and abs(z - height) <= 0.015)
            rows.append(
                {
                    "t": step / 200,
                    "id": step,
                    "subject": "other" if other else "current",
                    "good": good,
                }
            )
    contact_ids = {model.geom("object_geom").id, model.geom("tray").id}
    contact = any({int(c.geom1), int(c.geom2)} == contact_ids for c in data.contact)
    if case == "unseen-transient":
        # The object is supported on the tray but the observer feed drops its middle sample.
        rows = [rows[0], rows[-1]]
    initially = abs(pre_position[0]) <= 0.06 and abs(pre_position[2] - height) <= 0.015
    return (
        rows,
        {
            "positions": positions,
            "tray_contact": contact,
            "tolerance": [0.06, height, 0.015],
            "initially_satisfied": initially,
            "pre_position": pre_position,
        },
        before,
    )


def record():
    episodes = []
    for domain, families, runner in (
        ("deployment", ("square", "double", "increment"), deployment),
        ("placement", ("cube", "cylinder", "sphere"), placement),
    ):
        for index, family in enumerate(families):
            for case in CASES:
                rows, reference, initially = runner(family, case)
                if case.startswith("missing-"):
                    rows = rows[:1]
                if case == "duplicate":
                    rows = [rows[0], rows[0], rows[0]]
                episode_id = hashlib.sha256(
                    f"v1/{domain}/{family}/{case}".encode()
                ).hexdigest()[:16]
                episodes.append(
                    {
                        "id": episode_id,
                        "domain": domain,
                        "family": family,
                        "split": "heldout" if index else "development",
                        "case": case,
                        "requires_transition": case
                        in {"transition-required", "transition-achieved"},
                        "ack": True,
                        "before": initially,
                        "samples": rows,
                        "reference": reference,
                    }
                )
    return {"version": 1, "mujoco": mujoco.__version__, "episodes": episodes}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.write_text(
        json.dumps(record(), separators=(",", ":"), allow_nan=False) + "\n",
        encoding="utf-8",
    )
