from pathlib import Path

from worldstate_check.engine import verify
from worldstate_check.loader import load_spec
from worldstate_check.models import VerificationContext, Verdict


ROOT = Path(__file__).resolve().parents[1]


def run_example(name):
    spec_path = ROOT / "examples" / name
    spec = load_spec(spec_path)
    return verify(spec, VerificationContext(spec_path=spec_path, root=spec_path.parent))


def test_field_maintenance_example_verifies():
    assert run_example("field-maintenance.yaml").verdict is Verdict.VERIFIED


def test_spacecraft_example_is_intentional_failure():
    assert run_example("spacecraft-safe-mode.yaml").verdict is Verdict.NOT_VERIFIED
