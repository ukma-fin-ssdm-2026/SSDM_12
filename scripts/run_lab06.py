"""One local/CI command for Lab6 tests, coverage, reports and reproducibility data.

AI-assisted local preparation: Codex. A local result is not a GitHub Actions result.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import platform

# Fixed local commands; no shell command assembled from external input.
import subprocess  # nosec B404
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "docs/testing/lab06"


def main() -> int:
    REPORT.mkdir(parents=True, exist_ok=True)
    arguments = [
        "-m",
        "pytest",
        "-q",
        "--cov=api",
        "--cov=unislot",
        "--cov-branch",
        "--cov-fail-under=90",
        "--cov-report=term-missing",
        "--cov-report=xml:coverage.xml",
        "--cov-report=json:docs/testing/lab06/coverage.json",
        "--cov-report=html:docs/testing/lab06/htmlcov",
        "--junitxml=docs/testing/lab06/junit.xml",
    ]
    # Fixed interpreter and fixed pytest arguments, without a shell.
    completed = subprocess.run(  # noqa: S603  # nosec B603
        [sys.executable, *arguments],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    output = completed.stdout + completed.stderr
    # coverage.py creates an ignore-all file; this lab explicitly requires a report in Git.
    generated_ignore = REPORT / "htmlcov/.gitignore"
    if generated_ignore.exists():
        generated_ignore.unlink()
    (REPORT / "test-run.txt").write_text(output, encoding="utf-8")
    print(output, end="")
    files = sorted((ROOT / "src").rglob("*.py")) + sorted((ROOT / "tests").rglob("*.py"))
    data = {
        "date_kyiv": datetime.now(ZoneInfo("Europe/Kyiv")).isoformat(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "command": "python " + " ".join(arguments),
        "exit_code": completed.returncode,
        "coverage_gate_percent": 90,
        "coverage_scope": "all src/api and src/unislot, including MCP; no coverage exclusions added",
        "versions": {
            p: importlib.metadata.version(p)
            for p in ("pytest", "pytest-cov", "coverage", "hypothesis", "fastapi")
        },
        "files_sha256": {
            p.relative_to(ROOT).as_posix(): hashlib.sha256(
                p.read_bytes().replace(b"\r\n", b"\n")
            ).hexdigest()
            for p in files
        },
    }
    (REPORT / "run.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
