from pathlib import Path
import re


CI_WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "ci.yml"


def test_application_pytest_gate_is_not_shell_made_optional():
    """Application-test failures must propagate to the GitHub Actions job."""
    workflow = CI_WORKFLOW.read_text(encoding="utf-8")
    pytest_commands = [
        line.strip()
        for line in workflow.splitlines()
        if re.match(r"^\s*(?:python\s+-m\s+)?pytest\s+tests/", line)
    ]

    assert pytest_commands, "CI must execute the repository application test suite"
    assert all("|| true" not in command for command in pytest_commands), (
        "pytest failures must not be converted to a successful shell exit"
    )
