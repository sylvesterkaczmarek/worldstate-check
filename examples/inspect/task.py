"""Run with: inspect eval examples/inspect/task.py --model mockllm/model"""

from pathlib import Path

from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.solver import solver

from worldstate_check.inspect_scorer import worldstate_scorer
from worldstate_check.loader import load_spec


@solver
def recorded_episode():
    async def solve(state, generate):
        return state

    return solve


@task
def placement():
    root = Path(__file__).resolve().parents[1] / "placement"
    ids = ["placed", "slipped", "incomplete"]
    spec = load_spec(root / "spec.json")
    return Task(
        dataset=[
            Sample(id=name, input="Check placement after gripper withdrawal.")
            for name in ids
        ],
        solver=recorded_episode(),
        scorer=worldstate_scorer(spec, {name: str(root / name) for name in ids}),
    )
