#!/usr/bin/env python3
"""Кешоване віртуальне середовище для постійного self-hosted раннера (Лаб 10, бонус 2; QA-24).

Без кешу кожен job CI робить `python -m venv .venv` і повний `pip install` (≈ 50 с на job,
двічі на запуск: `build` і `reliability`). Наш раннер постійний, тож середовище можна
зберегти між запусками й брати готовим, поки не змінилися залежності.

* **Ключ кешу** — SHA-256 від версії Python і платформи, вимоги до pip, вмісту файла
  залежностей і всіх файлів, які він підключає через `-r`, та версії схеми кешу. Змінився
  будь-який із них — новий ключ, нове середовище.
* **Готовність** — маркер `.ready` із ключем пишеться останнім, тож недобудоване середовище
  (раннер вимкнули посеред `pip install`, як у запуску №86) ніколи не вважається готовим:
  його видаляють і будують заново. Перед кожним повторним використанням — `pip check`.
* **Ізоляція** — окремий каталог для кожної події (`--scope`): середовище, яке
  використовують запуски на `main`, ніколи не будує запуск PR.
* **Диск** — зберігаються лише `--keep` середовищ, що використовувались найпізніше
  (брак місця на диску раннера — причина запуску №58).

Середовище створюється одразу на своєму місці, а не в тимчасовій теці з перейменуванням:
venv не переносний — exe-обгортки в `Scripts` містять абсолютний шлях до python.exe.

Приклад у CI (PowerShell):

    python scripts/ci_venv.py --requirements requirements-testing.txt --pip "pip>=26.2" `
        --root "$env:RUNNER_TOOL_CACHE\\ssdm12-venv" --scope $env:EVENT --github-env

Друкує шлях до середовища; з `--github-env` дописує `VENV_DIR=<шлях>` у файл `$GITHUB_ENV`,
тож наступні кроки викликають `& "$env:VENV_DIR\\Scripts\\ruff.exe"`.
Коди виходу: 0 — середовище готове; 2 — неправильні аргументи або шлях; 1 — збій збірки.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import stat

# Fixed interpreter and fixed pip arguments; no shell, no user-built command line.
import subprocess  # nosec B404
import sys
import time
import venv
from collections.abc import Callable
from pathlib import Path

SCHEMA = "ssdm12-venv-v1"
MARKER = ".ready"
NAME = re.compile(r"^venv-[0-9a-f]{16}$")
SCOPE = re.compile(r"^[a-z_]{1,32}$")
INCLUDE = re.compile(r"^\s*(?:-r|--requirement)\s*=?\s*(\S+)")


class VenvError(RuntimeError):
    """Неправильні аргументи або шлях (код виходу 2)."""


class BuildError(VenvError):
    """Середовище не вдалося зібрати або воно не проходить pip check (код виходу 1)."""


def requirement_files(path: Path, seen: set[Path] | None = None) -> list[Path]:
    """Файл залежностей і всі файли, які він підключає через `-r` (рекурсивно, без циклів)."""
    seen = set() if seen is None else seen
    path = path.resolve()
    if path in seen:
        return []
    if not path.is_file():
        raise VenvError(f"не знайдено файл залежностей: {path.name}")
    seen.add(path)
    files = [path]
    for line in path.read_text(encoding="utf-8").splitlines():
        match = INCLUDE.match(line)
        if match:
            files += requirement_files(path.parent / match.group(1), seen)
    return files


def cache_key(requirements: Path, pip_spec: str, python: str | None = None) -> str:
    """16 hex-символів SHA-256: Python, платформа, pip, вміст усіх файлів залежностей."""
    digest = hashlib.sha256()
    for part in (SCHEMA, python or sys.version, sys.platform, pip_spec):
        digest.update(part.encode("utf-8") + b"\0")
    root = requirements.resolve().parent
    for file in requirement_files(requirements):
        name = file.relative_to(root).as_posix() if file.is_relative_to(root) else file.name
        # \r\n і \n дають той самий ключ: git на Windows може видати будь-яке з них.
        digest.update(name.encode("utf-8") + b"\0" + file.read_bytes().replace(b"\r\n", b"\n"))
    return digest.hexdigest()[:16]


def python_in(env_dir: Path) -> Path:
    """Шлях до python усередині venv на цій ОС."""
    if os.name == "nt":
        return env_dir / "Scripts" / "python.exe"
    return env_dir / "bin" / "python"


def _run(args: list[str]) -> bool:
    completed = subprocess.run(args, check=False)  # noqa: S603  # nosec B603
    return completed.returncode == 0


def build_with_pip(env_dir: Path, requirements: Path, pip_spec: str) -> None:
    """Справжня збірка: venv із pip, оновлення pip, встановлення залежностей."""
    venv.create(env_dir, with_pip=True, clear=True)
    python = str(python_in(env_dir))
    pip = [python, "-m", "pip", "install", "--disable-pip-version-check", "-q"]
    if not _run([*pip, pip_spec]):
        raise BuildError("не вдалося оновити pip")
    if not _run([*pip, "-r", str(requirements)]):
        raise BuildError("не вдалося встановити залежності")


def check_with_pip(env_dir: Path) -> bool:
    """`pip check`: усі встановлені пакети сумісні між собою."""
    python = python_in(env_dir)
    return python.is_file() and _run([str(python), "-m", "pip", "check", "-q"])


def _on_rm_error(function, path, _excinfo) -> None:
    """Windows не видаляє файли «лише для читання» — знімаємо атрибут і пробуємо ще раз."""
    Path(path).chmod(stat.S_IWRITE)
    function(path)


def remove_env(root: Path, env_dir: Path) -> None:
    """Видаляє лише власний каталог кешу `venv-<16 hex>` безпосередньо в root."""
    target, parent = env_dir.resolve(), root.resolve()
    if target.parent != parent or not NAME.fullmatch(target.name):
        raise VenvError(f"відмовляюся видаляти чужий каталог: {env_dir}")
    if target.exists():
        shutil.rmtree(target, onexc=_on_rm_error)


def prune(root: Path, keep: int, current: Path) -> list[Path]:
    """Залишає `keep` середовищ, що використовувались найпізніше; поточне — завжди."""
    candidates = [
        p for p in root.iterdir() if p.is_dir() and NAME.fullmatch(p.name) and p != current
    ]

    def last_used(path: Path) -> float:
        marker = path / MARKER
        return marker.stat().st_mtime if marker.exists() else 0.0

    candidates.sort(key=last_used, reverse=True)
    removed = candidates[max(0, keep - 1) :]
    for path in removed:
        remove_env(root, path)
    return removed


def ensure(
    root: Path,
    key: str,
    build: Callable[[Path], None],
    check: Callable[[Path], bool],
    keep: int = 3,
) -> tuple[Path, bool]:
    """Повертає (шлях, чи було влучання в кеш); за потреби будує середовище заново."""
    root.mkdir(parents=True, exist_ok=True)
    env_dir = root / f"venv-{key}"
    marker = env_dir / MARKER
    hit = marker.is_file() and marker.read_text(encoding="utf-8").strip() == key
    if hit and not check(env_dir):
        print(f"[venv] {env_dir.name}: pip check не пройшов — перебудовую")
        hit = False
    if not hit:
        remove_env(root, env_dir)  # недобудоване або зіпсоване середовище
        build(env_dir)
        if not check(env_dir):
            raise BuildError("щойно зібране середовище не проходить pip check")
        marker.write_text(key + "\n", encoding="utf-8")  # маркер — останнім
    os.utime(marker)  # «використано зараз» — для prune
    prune(root, keep, env_dir)
    return env_dir, hit


def _root(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        raise argparse.ArgumentTypeError("--root має бути абсолютним шляхом")
    if path.resolve().is_relative_to(Path.cwd().resolve()):
        # actions/checkout чистить робочий каталог (git clean -ffdx) — кеш там не виживе.
        raise argparse.ArgumentTypeError("--root не може бути всередині репозиторію")
    return path


def _scope(value: str) -> str:
    if not SCOPE.fullmatch(value):
        raise argparse.ArgumentTypeError("--scope: лише малі латинські літери й _")
    return value


def main(
    argv: list[str] | None = None,
    *,
    build: Callable[[Path, Path, str], None] = build_with_pip,
    check: Callable[[Path], bool] = check_with_pip,
) -> int:
    """Точка входу CLI; build і check підміняють тести, щоб не ставити пакети."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--requirements", type=Path, required=True)
    parser.add_argument("--pip", default="pip>=26.2", help="вимога до самого pip")
    parser.add_argument("--root", type=_root, required=True, help="каталог кешу поза репозиторієм")
    parser.add_argument("--scope", type=_scope, default="default", help="подія: push, pull_request")
    parser.add_argument("--keep", type=int, default=3, choices=range(1, 11))
    parser.add_argument("--github-env", action="store_true", help="дописати VENV_DIR у $GITHUB_ENV")
    args = parser.parse_args(argv)
    started = time.monotonic()
    try:
        requirements = args.requirements.resolve()
        if not requirements.is_relative_to(Path.cwd().resolve()):
            raise VenvError("файл залежностей має бути в репозиторії")
        key = cache_key(requirements, args.pip)
        env_dir, hit = ensure(
            args.root / args.scope,
            key,
            lambda path: build(path, requirements, args.pip),
            check,
            keep=args.keep,
        )
    except BuildError as error:
        print(f"[venv] помилка збірки: {error}", file=sys.stderr)
        return 1
    except VenvError as error:
        print(f"[venv] помилка: {error}", file=sys.stderr)
        return 2
    seconds = time.monotonic() - started
    state = "влучання в кеш" if hit else "промах кешу — зібрано заново"
    print(f"[venv] {state}: {env_dir} ({seconds:.1f} с)")
    if args.github_env:
        target = os.environ.get("GITHUB_ENV")
        if not target:
            print("[venv] помилка: GITHUB_ENV не задано", file=sys.stderr)
            return 2
        with Path(target).open("a", encoding="utf-8") as env_file:
            env_file.write(f"VENV_DIR={env_dir}\n")
    print(env_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
