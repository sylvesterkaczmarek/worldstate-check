import inspect

import worldstate_check
from worldstate_check import VerificationReport, Verdict, verify_spec, verify_spec_data


def test_public_api_surface_is_small_and_stable():
    assert worldstate_check.__all__ == [
        "SpecError",
        "VerificationReport",
        "Verdict",
        "verify_spec",
        "verify_spec_data",
    ]

    for function in (verify_spec, verify_spec_data):
        signature = inspect.signature(function)
        assert signature.parameters["allow_outside_root"].default is False
        assert signature.parameters["allow_command"].default is False
        assert signature.parameters["allow_network"].default is False
        assert signature.parameters["wait_seconds"].default == 0.0
        assert signature.parameters["poll_interval"].default == 0.5


def test_public_api_verifies_spec_file(tmp_path):
    (tmp_path / "state.json").write_text('{"status":"complete"}', encoding="utf-8")
    spec = tmp_path / "worldstate.yaml"
    spec.write_text(
        "version: 1\n"
        "task: embedded-check\n"
        "checks:\n"
        "  - id: state\n"
        "    type: json\n"
        "    path: state.json\n"
        "    field: status\n"
        "    operator: eq\n"
        "    value: complete\n",
        encoding="utf-8",
    )

    report = verify_spec(spec)

    assert isinstance(report, VerificationReport)
    assert report.verdict is Verdict.VERIFIED
    assert report.task == "embedded-check"


def test_public_api_verifies_in_memory_spec(tmp_path):
    (tmp_path / "state.json").write_text('{"status":"complete"}', encoding="utf-8")
    specification = {
        "version": 1,
        "task": "in-memory-check",
        "checks": [
            {
                "id": "state",
                "type": "json",
                "path": "state.json",
                "field": "status",
                "operator": "eq",
                "value": "complete",
            }
        ],
    }

    report = verify_spec_data(specification, root=tmp_path)

    assert isinstance(report, VerificationReport)
    assert report.verdict is Verdict.VERIFIED
    assert report.task == "in-memory-check"
    assert report.required_passed == 1
    assert report.required_total == 1


def test_public_api_file_and_memory_paths_share_verdict_logic(tmp_path):
    (tmp_path / "state.json").write_text('{"status":"wrong"}', encoding="utf-8")
    specification = {
        "version": 1,
        "task": "same-engine",
        "checks": [
            {
                "id": "state",
                "type": "json",
                "path": "state.json",
                "field": "status",
                "operator": "eq",
                "value": "complete",
            }
        ],
    }
    spec = tmp_path / "worldstate.yaml"
    spec.write_text(
        "version: 1\n"
        "task: same-engine\n"
        "checks:\n"
        "  - id: state\n"
        "    type: json\n"
        "    path: state.json\n"
        "    field: status\n"
        "    operator: eq\n"
        "    value: complete\n",
        encoding="utf-8",
    )

    file_report = verify_spec(spec)
    memory_report = verify_spec_data(specification, root=tmp_path)

    assert file_report.verdict is memory_report.verdict is Verdict.NOT_VERIFIED
    assert [result.status for result in file_report.results] == [
        result.status for result in memory_report.results
    ]


def test_public_api_keeps_command_checks_opt_in(tmp_path):
    specification = {
        "version": 1,
        "task": "command-boundary",
        "checks": [
            {
                "id": "command",
                "type": "command",
                "argv": ["python", "-c", "print(1)"],
                "exit_code": 0,
            }
        ],
    }

    report = verify_spec_data(specification, root=tmp_path)

    assert report.verdict is Verdict.UNCERTAIN
    assert report.results[0].status.value == "UNKNOWN"
