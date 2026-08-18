from worldstate_check import VerificationReport, Verdict, verify_spec


def test_public_api_verifies_spec(tmp_path):
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


def test_public_api_keeps_command_checks_opt_in(tmp_path):
    spec = tmp_path / "worldstate.yaml"
    spec.write_text(
        "version: 1\n"
        "task: command-boundary\n"
        "checks:\n"
        "  - id: command\n"
        "    type: command\n"
        "    argv: [python, -c, 'print(1)']\n"
        "    exit_code: 0\n",
        encoding="utf-8",
    )

    report = verify_spec(spec)

    assert report.verdict is Verdict.UNCERTAIN
    assert report.results[0].status.value == "UNKNOWN"
