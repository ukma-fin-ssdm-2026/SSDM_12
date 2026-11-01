"""Окремий PostgreSQL-кластер для локальної розробки й справжніх інтеграційних тестів."""

from __future__ import annotations

import json
import os
import secrets
import shutil
import socket

# Fixed PostgreSQL binaries, no shell.
import subprocess  # nosec B404
from pathlib import Path

import psycopg
from psycopg import sql
from sqlalchemy.engine import URL


def postgres_bin() -> Path:
    candidate = os.environ.get("UNISLOT_POSTGRES_BIN")
    if candidate and (Path(candidate) / "initdb.exe").exists():
        return Path(candidate)
    found = shutil.which("initdb")
    if found:
        return Path(found).parent
    roots = (
        Path(os.environ.get("PROGRAMFILES", "C:/Program Files")) / "PostgreSQL",
        Path("/usr/lib/postgresql"),
    )
    for root in roots:
        paths = sorted(root.glob("*/bin/initdb*"), reverse=True) if root.exists() else []
        if paths:
            return paths[0].parent
    raise RuntimeError("PostgreSQL binaries required; set UNISLOT_POSTGRES_BIN")


def command(binary: Path, args: list[str]) -> None:
    # Paths/arguments are passed directly; no interpolation into a shell.
    directory = Path(args[args.index("-D") + 1]).parent
    # Windows child postgres inherits handles: a PIPE would keep communicate() open.
    with (directory / "bootstrap.log").open("ab") as output:
        run = subprocess.run(  # noqa: S603 -- fixed PostgreSQL binary, no shell
            [str(binary), *args], stdout=output, stderr=subprocess.STDOUT, timeout=45, check=False
        )  # nosec B603
    if run.returncode:
        raise RuntimeError(f"{binary.name} failed; inspect the local PostgreSQL log")


class LocalCluster:
    """Керує лише власним новим datadir, не системним PostgreSQL-сервісом."""

    def __init__(self, directory: Path, *, port: int | None = None) -> None:
        self.directory = directory.resolve()
        self.bin = postgres_bin()
        self.started = False
        self.databases: set[str] = set()
        self.directory.mkdir(parents=True, exist_ok=True)
        config = self.directory / "local-connection.json"
        if config.exists():
            values = json.loads(config.read_text(encoding="utf-8"))
            self.port, self.password = values["port"], values["password"]
        else:
            if (self.directory / "data").exists():
                raise ValueError("refusing to adopt an unknown PostgreSQL datadir")
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", port or 0))
                self.port = sock.getsockname()[1]
            self.password = secrets.token_urlsafe(32)
            config.write_text(
                json.dumps({"port": self.port, "password": self.password}), encoding="utf-8"
            )

    def _exe(self, name: str) -> Path:
        return self.bin / (name + ".exe" if os.name == "nt" else name)

    def start(self) -> None:
        data = self.directory / "data"
        if not (data / "PG_VERSION").exists():
            pwfile = self.directory / "init-password"
            pwfile.write_text(self.password, encoding="utf-8")
            try:
                command(
                    self._exe("initdb"),
                    [
                        "-D",
                        str(data),
                        "-U",
                        "unislot_owner",
                        "--encoding=UTF8",
                        "--locale=C",
                        "-A",
                        "scram-sha-256",
                        "--pwfile",
                        str(pwfile),
                    ],
                )
            finally:
                pwfile.unlink(missing_ok=True)
        status = subprocess.run(  # noqa: S603 -- fixed PostgreSQL binary, no shell
            [str(self._exe("pg_ctl")), "-D", str(data), "status"], capture_output=True, check=False
        )  # nosec B603
        if status.returncode:
            command(
                self._exe("pg_ctl"),
                [
                    "-D",
                    str(data),
                    "-l",
                    str(self.directory / "postgres.log"),
                    "-o",
                    f"-h 127.0.0.1 -p {self.port}",
                    "-w",
                    "start",
                ],
            )
        self.started = True

    def stop(self) -> None:
        if self.started:
            command(
                self._exe("pg_ctl"),
                ["-D", str(self.directory / "data"), "-m", "fast", "-w", "stop"],
            )
            self.started = False

    def owner_connection(self):
        return psycopg.connect(
            host="127.0.0.1",
            port=self.port,
            dbname="postgres",
            user="unislot_owner",
            password=self.password,
            autocommit=True,
        )

    def create_database(self, name: str, role: str) -> tuple[str, str]:
        password = secrets.token_urlsafe(32)
        with self.owner_connection() as conn:
            conn.execute(
                sql.SQL(
                    "CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS"
                ).format(sql.Identifier(role), sql.Literal(password))
            )
            conn.execute(
                sql.SQL("CREATE DATABASE {} OWNER unislot_owner").format(sql.Identifier(name))
            )
        self.databases.add(name)

        def url(user: str, secret: str) -> str:
            return URL.create(
                "postgresql+psycopg",
                username=user,
                password=secret,
                host="127.0.0.1",
                port=self.port,
                database=name,
            ).render_as_string(hide_password=False)

        return url("unislot_owner", self.password), url(role, password)

    def drop_database(self, name: str, role: str) -> None:
        if name not in self.databases:
            raise ValueError("refusing to delete a database not created by this cluster object")
        with self.owner_connection() as conn:
            conn.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
            conn.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))
        self.databases.remove(name)
