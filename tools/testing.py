"""run_tests: runs the project's test suite in a subprocess using a fixed command allowlist."""
from __future__ import annotations

import importlib.util
import os
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass

from core.logging import get_logger
from core.security import Workspace

log = get_logger("tools.testing")
MAX_OUTPUT_CHARS = 8000


@dataclass
class TestResult:
    __test__ = False  # not a pytest test class

    command: str
    status: str  # passed | failed | no_tests | timeout | error
    passed: int = 0
    failed: int = 0
    errors: int = 0
    duration: float = 0.0
    output: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def detect_command() -> list[str]:
    """Prefer `pytest -q`; fall back to stdlib unittest when pytest is not installed."""
    if importlib.util.find_spec("pytest"):
        return [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"]
    return [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", "."]


def display_command(cmd: list[str]) -> str:
    return "pytest -q" if "pytest" in cmd else "python -m unittest discover -s tests -t ."


def _parse(cmd: list[str], output: str) -> tuple[int, int, int]:
    if "pytest" in cmd:
        counts = {"passed": 0, "failed": 0, "error": 0}
        for number, word in re.findall(r"(\d+) (passed|failed|errors?)\b", output.splitlines()[-1] if output.strip() else ""):
            counts["error" if word.startswith("error") else word] = int(number)
        return counts["passed"], counts["failed"], counts["error"]
    ran = re.search(r"Ran (\d+) tests?", output)
    total = int(ran.group(1)) if ran else 0
    failures = int(m.group(1)) if (m := re.search(r"failures=(\d+)", output)) else 0
    errors = int(m.group(1)) if (m := re.search(r"errors=(\d+)", output)) else 0
    return max(total - failures - errors, 0), failures, errors


def run_tests(ws: Workspace, timeout: int = 60) -> TestResult:
    cmd = detect_command()
    shown = display_command(cmd)
    # Minimal environment: API keys and other secrets are NOT passed to the code under test.
    env = {"PATH": os.environ.get("PATH", ""), "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": str(ws.root)}
    for key in ("SYSTEMROOT", "LANG", "LC_ALL", "TMPDIR", "TEMP"):
        if key in os.environ:
            env[key] = os.environ[key]
    log.info("run_tests: %s", shown)
    start = time.monotonic()
    try:
        proc = subprocess.run(cmd, cwd=ws.root, env=env, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return TestResult(shown, "timeout", duration=timeout, output=f"Test run exceeded {timeout}s and was stopped.")
    except OSError as exc:
        return TestResult(shown, "error", output=f"Could not start test process: {exc}")
    duration = round(time.monotonic() - start, 2)
    output = (proc.stdout + ("\n" + proc.stderr if proc.stderr.strip() else "")).strip()
    output = output[-MAX_OUTPUT_CHARS:]
    passed, failed, errors = _parse(cmd, proc.stdout if "pytest" in cmd else proc.stderr + proc.stdout)
    if proc.returncode == 0 and passed > 0:
        status = "passed"
    elif proc.returncode == 5 or (proc.returncode == 0 and passed == 0):
        status = "no_tests"
    else:
        status = "failed"
    log.info("run_tests result: %s (%d passed, %d failed, %d errors)", status, passed, failed, errors)
    return TestResult(shown, status, passed, failed, errors, duration, output)
