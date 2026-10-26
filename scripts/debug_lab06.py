"""Відтворення навмисного дефекту дедлайну в одноразовій копії проєкту.

Робочі джерела не змінюються. Підготовка й автоматизована перевірка: Codex.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import shutil

# Команди фіксовані; текст зовнішнього вводу не передається командній оболонці.
import subprocess  # nosec B404
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path("src/unislot/booking/domain/rules.py")
EVIDENCE = ROOT / "docs/testing/lab06/evidence"


def main() -> int:
    """Запускає RED і GREEN у тимчасовій копії та звіряє хеш робочого домену."""
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    original_bytes = (ROOT / SOURCE).read_bytes()
    original = original_bytes.decode("utf-8").replace("\r\n", "\n")
    needle = "if now > deadline:"
    if original.count(needle) != 1:
        raise RuntimeError("Місце внесення дефекту змінилося; перевірте правила перед запуском")
    broken = original.replace(needle, "if now >= deadline:")
    patch = "".join(
        difflib.unified_diff(
            original.splitlines(True),
            broken.splitlines(True),
            fromfile=f"a/{SOURCE.as_posix()}",
            tofile=f"b/{SOURCE.as_posix()}",
        )
    )
    patch_path = ROOT / "docs/testing/debug-challenge/lab06-deadline.patch"
    patch_path.parent.mkdir(parents=True, exist_ok=True)
    patch_path.write_text(patch, encoding="utf-8")
    temp_root = ROOT / ".lab06-tmp"
    temp_root.mkdir(exist_ok=True)
    results = []
    with tempfile.TemporaryDirectory(prefix="deadline-", dir=temp_root) as name:
        copied = Path(name).resolve()
        if not copied.is_relative_to(temp_root.resolve()):
            raise RuntimeError("Тимчасова копія вийшла за межі каталогу вправи")
        for folder in ("src", "tests"):
            shutil.copytree(
                ROOT / folder,
                copied / folder,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )
        shutil.copy2(ROOT / "pyproject.toml", copied / "pyproject.toml")
        test_file = "tests/unit/test_booking_service.py"
        command = [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            f"{test_file}::test_cancel_exact_deadline_allowed",
            f"{test_file}::test_can_cancel_view_agrees_with_command_at_exact_deadline",
        ]
        environment = dict(os.environ, PYTHONPATH=str(copied / "src"), UNISLOT_EXPORT_OPENAPI="0")
        for label, content, expected in (("red", broken, 1), ("green", original, 0)):
            (copied / SOURCE).write_text(content, encoding="utf-8")
            # Інтерпретатор і тести задані явно; оболонка та зовнішні аргументи не потрібні.
            completed = subprocess.run(  # noqa: S603  # nosec B603
                command,
                cwd=copied,
                env=environment,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            (EVIDENCE / f"debug-{label}.txt").write_text(
                completed.stdout + completed.stderr, encoding="utf-8"
            )
            results.append({"stage": label, "exit_code": completed.returncode})
            if completed.returncode != expected:
                raise RuntimeError(f"Неочікуваний результат стадії {label}; перевірте логи")
    unchanged = hashlib.sha256((ROOT / SOURCE).read_bytes()).hexdigest()
    before = hashlib.sha256(original_bytes).hexdigest()
    result = {
        "executed_utc": datetime.now(UTC).isoformat(),
        "source": SOURCE.as_posix(),
        "mutation": "заміна > на >= у перевірці збереженого дедлайну скасування",
        "stages": results,
        "source_sha256_before": before,
        "source_sha256_after": unchanged,
        "working_source_unchanged": before == unchanged,
        "actor": "Codex; автоматизована вправа в окремій копії, без засвідчення участі студента",
    }
    (EVIDENCE / "debug-results.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result))
    return 0 if before == unchanged else 1


if __name__ == "__main__":
    raise SystemExit(main())
