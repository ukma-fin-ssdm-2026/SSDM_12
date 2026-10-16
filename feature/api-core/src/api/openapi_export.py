"""Генерація документації API з коду: `docs/api/openapi-generated.yaml` і `errors.html`.

Три способи запуску — усі викликають ті самі функції цього модуля:

1. старт сервера (`api.main.lifespan`) — для циклу Code-First на своїй машині;
2. `python scripts/export_openapi.py` — записати файли без запуску сервера;
3. `python scripts/export_openapi.py --check` — у CI: порівняти закомічені файли з
   тим, що генерує код; розходження → код виходу 1 (специфікацію редагували вручну
   або забули перегенерувати).

Вивід детермінований: порядок ключів — як у FastAPI, приклади в схемах сталі,
версії бібліотек закріплено в `requirements.txt`.
"""

from __future__ import annotations

import argparse
import difflib
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from api.errors import render_error_catalog_html

if TYPE_CHECKING:
    from fastapi import FastAPI

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCS_API = REPO_ROOT / "docs" / "api"
SPEC_NAME = "openapi-generated.yaml"
ERRORS_NAME = "errors.html"
SPEC_HEADER = (
    "# ЗГЕНЕРОВАНО з коду src/api/ (FastAPI, Code-First). Не редагуйте вручну:\n"
    "# змініть код і запустіть `python scripts/export_openapi.py` або сервер.\n"
)


class _NoAliasDumper(yaml.SafeDumper):
    """YAML без якорів &id001: однакові фрагменти виписуються повністю, читабельно."""

    def ignore_aliases(self, data: Any) -> bool:
        return True


def _str_representer(dumper: yaml.SafeDumper, data: str) -> yaml.ScalarNode:
    """Багаторядкові описи — блоком `|`, як їх написано в докстрінгах, без лапок і \\n."""
    style = "|" if "\n" in data else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=style)


_NoAliasDumper.add_representer(str, _str_representer)


def render_spec_yaml(app: FastAPI) -> str:
    """Специфікація OpenAPI застосунку у YAML."""
    body = yaml.dump(
        app.openapi(), Dumper=_NoAliasDumper, sort_keys=False, allow_unicode=True, width=100
    )
    return SPEC_HEADER + body


def render_artifacts(app: FastAPI) -> dict[str, str]:
    """Усі згенеровані файли документації: ім'я файлу → вміст."""
    return {SPEC_NAME: render_spec_yaml(app), ERRORS_NAME: render_error_catalog_html()}


def write_artifacts(app: FastAPI, out_dir: Path = DOCS_API) -> list[Path]:
    """Записує файли документації в `out_dir`; повертає шляхи записаних файлів."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name, content in render_artifacts(app).items():
        path = out_dir / name
        path.write_text(content, encoding="utf-8", newline="\n")
        written.append(path)
    return written


def check_artifacts(app: FastAPI, out_dir: Path = DOCS_API) -> list[str]:
    """Порівнює файли в `out_dir` зі згенерованими; повертає опис розходжень."""
    problems = []
    for name, expected in render_artifacts(app).items():
        path = out_dir / name
        actual = path.read_text(encoding="utf-8") if path.is_file() else ""
        if actual != expected:
            diff = difflib.unified_diff(
                actual.splitlines(),
                expected.splitlines(),
                f"{name} (у репозиторії)",
                f"{name} (з коду)",
                lineterm="",
            )
            problems.append("\n".join(list(diff)[:60]))
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Генерація OpenAPI з коду UniSlot API.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="не записувати, а перевірити, що файли в docs/api/ збігаються з кодом",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=DOCS_API,
        help="куди записати файли (за замовчуванням docs/api/)",
    )
    args = parser.parse_args(argv)

    from api.main import create_app  # пізній імпорт: main сам імпортує цей модуль

    app = create_app()
    if args.check:
        problems = check_artifacts(app, args.out_dir)
        if problems:
            print("[FAIL] Документація API розходиться з кодом:\n")
            print("\n\n".join(problems))
            print("\nЗапустіть `python scripts/export_openapi.py` і закомітьте змінені файли.")
            return 1
        print(f"[ ok ] {SPEC_NAME} і {ERRORS_NAME} збігаються з кодом.")
        return 0
    for path in write_artifacts(app, args.out_dir):
        print(f"[ ok ] записано {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
