"""Run Cosmic Ray on resource capacity rules in a disposable copy; preserve real results.

Requires requirements-mutation.txt. AI-assisted local tooling: Codex.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import shlex
import shutil

# Fixed local commands; no shell command assembled from external input.
import subprocess  # nosec B404
import sys
import tempfile
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from cosmic_ray import commands
from cosmic_ray.config import ConfigDict
from cosmic_ray.work_db import use_db

ROOT = Path(__file__).resolve().parents[1]
MODULE = Path("src/api/resource_rules.py")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", choices=("before", "after"), required=True)
    label = parser.parse_args().label
    evidence = ROOT / "docs/testing/lab06/evidence"
    temp_root = ROOT / ".lab06-tmp"
    temp_root.mkdir(exist_ok=True)
    original = (ROOT / MODULE).read_bytes()
    with tempfile.TemporaryDirectory(prefix="cosmic-ray-", dir=temp_root) as name:
        copied = Path(name).resolve()
        if not copied.is_relative_to(temp_root.resolve()):
            raise RuntimeError("Temporary path escaped the workspace")
        for directory in ("src", "tests"):
            shutil.copytree(
                ROOT / directory,
                copied / directory,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )
        shutil.copy2(ROOT / "pyproject.toml", copied / "pyproject.toml")
        previous = Path.cwd()
        try:
            os.chdir(copied)
            os.environ["PYTHONIOENCODING"] = "utf-8"
            os.environ["UNISLOT_EXPORT_OPENAPI"] = "0"
            quote = subprocess.list2cmdline if os.name == "nt" else shlex.join
            command = quote(
                [
                    Path(sys.executable).as_posix(),
                    "-m",
                    "pytest",
                    "-q",
                    "tests/unit/test_resource_rules.py",
                    *(
                        ["-k", "not bool_capacity and not strict_resource_type"]
                        if label == "before"
                        else []
                    ),
                ]
            )
            config = ConfigDict(
                {"test-command": command, "timeout": 15, "distributor": {"name": "local"}}
            )
            with use_db(copied / "mutation.sqlite") as database:
                commands.init([MODULE], database, {})
                commands.execute(database, config)
                rows = []
                for item, result in database.completed_work_items:
                    mutation = item.mutations[0]
                    rows.append(
                        {
                            "operator": mutation.operator_name,
                            "occurrence": mutation.occurrence,
                            "start_pos": mutation.start_pos,
                            "end_pos": mutation.end_pos,
                            "worker_outcome": result.worker_outcome.value,
                            "outcome": result.test_outcome.value if result.test_outcome else None,
                            "diff": result.diff,
                            "output": result.output,
                        }
                    )
        finally:
            os.chdir(previous)
    if (ROOT / MODULE).read_bytes() != original:
        raise RuntimeError("Working source changed unexpectedly")
    counts = Counter(r["outcome"] for r in rows)
    valid = counts["killed"] + counts["survived"]
    data = {
        "executed_utc": datetime.now(UTC).isoformat(),
        "tool": "cosmic-ray",
        "version": importlib.metadata.version("cosmic-ray"),
        "module": MODULE.as_posix(),
        "source_sha256": hashlib.sha256(original).hexdigest(),
        "scope": "all default Cosmic Ray operators on resource_rules; targeted unit tests",
        "counts": dict(counts),
        "total": len(rows),
        "mutation_score": 100 * counts["killed"] / valid if valid else None,
        "working_source_unchanged": True,
        "results": rows,
    }
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / f"mutation-{label}.json").write_text(
        json.dumps(data, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({k: v for k, v in data.items() if k != "results"}))
    return 0 if valid and not counts.get("incompetent") else 1


if __name__ == "__main__":
    raise SystemExit(main())
