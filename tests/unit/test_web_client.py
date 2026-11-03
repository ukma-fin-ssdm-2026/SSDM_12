"""JavaScript helpers are tested by Node's built-in runner, without npm packages."""

import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.req("FR-012", "FR-030", "SEC-002", "USAB-001", "QA-09")


def test_browser_client_time_csrf_and_pagination_contracts():
    node = shutil.which("node")
    assert node, "Node.js 22+ required for the browser client tests (see README)"
    root = Path(__file__).resolve().parents[2]
    # Fixed executable and test path; no shell and no credentials in child arguments.
    result = subprocess.run(  # noqa: S603 -- fixed Node executable and repository test script
        [node, "--test", str(root / "tests/web/client.test.mjs")],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
