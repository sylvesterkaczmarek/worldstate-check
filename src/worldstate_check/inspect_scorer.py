"""Optional Inspect AI scorer for observations supplied by the evaluation harness."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from pathlib import Path

from inspect_ai.scorer import Score, mean, scorer

from .api import verify_spec_data
from .loader import validate_spec
from .models import Verdict


@scorer(
    metrics=[{"verified": [mean()], "not_verified": [mean()], "uncertain": [mean()]}]
)
def worldstate_scorer(specification: dict, roots: dict[str, str]):
    """Map each sample ID to its evaluator-owned evidence directory."""
    spec = deepcopy(specification)
    validate_spec(spec)
    paths = {str(key): Path(path).resolve() for key, path in roots.items()}

    async def score(state, target):
        root = paths.get(str(state.sample_id))
        if root is None or not root.is_dir():
            raise ValueError(
                f"missing observer directory for sample {state.sample_id!r}"
            )
        report = await asyncio.to_thread(verify_spec_data, spec, root=root)
        return Score(
            value={
                verdict.value.lower(): int(report.verdict is verdict)
                for verdict in Verdict
            },
            answer=report.verdict.value,
            explanation="\n".join(
                f"{r.check_id}: {r.status.value} ({r.reason_code})"
                for r in report.results
            ),
            metadata={
                "specification_sha256": report.specification_sha256,
                "checks": [
                    {
                        "id": r.check_id,
                        "status": r.status.value,
                        "reason": r.reason_code,
                    }
                    for r in report.results
                ],
            },
        )

    return score
