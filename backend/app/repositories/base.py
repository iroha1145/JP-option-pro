"""SQLite connection discipline shared by every repository.

Inherited from the proven old-project rules:
- WAL journal, synchronous=FULL, busy_timeout=5000, foreign_keys=ON;
  initialization fails if WAL cannot be established.
- Writers use explicit ``BEGIN IMMEDIATE`` transactions; connections are
  per-call, never pooled.
- Readers open ``file:...?mode=ro`` URIs with ``query_only=ON`` so a
  read-only process can never create or migrate a database by accident.
- The normalized DDL's SHA-256 is stored in a version table and verified on
  every open — schema drift raises instead of silently coexisting.
"""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


class SchemaVersionError(RuntimeError):
    pass


def schema_checksum(ddl_statements: tuple[str, ...]) -> str:
    normalized = "\n".join(" ".join(statement.split()) for statement in ddl_statements)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class SQLiteRepository:
    SCHEMA_NAME = "base"
    SCHEMA_VERSION = "v0"
    DDL: tuple[str, ...] = ()
    #: 明示的な前方マイグレーション: {旧version: (追加DDL群, 新version)}。
    #: 追加DDL適用後のスキーマは新規作成と同一でなければならない（検証は
    #: バージョン文字列と新チェックサムの保存で行う）。チェーンに無い旧版は
    #: 従来通り SchemaVersionError で拒否する。
    MIGRATIONS: dict[str, tuple[tuple[str, ...], str]] = {}

    def __init__(self, db_path: Path, *, read_only: bool = False) -> None:
        self._db_path = Path(db_path)
        self._read_only = bool(read_only)
        self._checksum = schema_checksum(self.DDL)

    @property
    def db_path(self) -> Path:
        return self._db_path

    @property
    def read_only(self) -> bool:
        return self._read_only

    def initialize(self) -> None:
        if self._read_only:
            raise RuntimeError("read-only repository cannot initialize a schema")
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect_rw() as connection:
            journal_mode = connection.execute("PRAGMA journal_mode=WAL").fetchone()[0]
            if str(journal_mode).lower() != "wal":
                raise RuntimeError(f"could not enable WAL on {self._db_path.name}")
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS {self.SCHEMA_NAME}_schema (
                        id INTEGER PRIMARY KEY CHECK (id = 1),
                        version TEXT NOT NULL,
                        checksum TEXT NOT NULL,
                        applied_at TEXT NOT NULL
                    )
                    """
                )
                row = connection.execute(
                    f"SELECT version, checksum FROM {self.SCHEMA_NAME}_schema WHERE id = 1"
                ).fetchone()
                if row is None:
                    for statement in self.DDL:
                        connection.execute(statement)
                    connection.execute(
                        f"INSERT INTO {self.SCHEMA_NAME}_schema (id, version, checksum, applied_at)"
                        " VALUES (1, ?, ?, ?)",
                        (self.SCHEMA_VERSION, self._checksum, utc_now_iso()),
                    )
                else:
                    version = str(row[0])
                    # 前方マイグレーション: 既知の旧版なら追加DDLを適用して
                    # バージョンを進める。1 トランザクション内なので途中失敗は
                    # 丸ごとロールバックされる。
                    migrated = False
                    while version != self.SCHEMA_VERSION and version in self.MIGRATIONS:
                        statements, next_version = self.MIGRATIONS[version]
                        for statement in statements:
                            connection.execute(statement)
                        version = next_version
                        migrated = True
                    if version != self.SCHEMA_VERSION:
                        raise SchemaVersionError(
                            f"{self._db_path.name}: stored schema {row[0]}/{row[1][:12]} does not match"
                            f" code {self.SCHEMA_VERSION}/{self._checksum[:12]} and no migration path exists"
                        )
                    if migrated:
                        connection.execute(
                            f"UPDATE {self.SCHEMA_NAME}_schema SET version=?, checksum=?, applied_at=?"
                            " WHERE id=1",
                            (self.SCHEMA_VERSION, self._checksum, utc_now_iso()),
                        )
                    elif row[1] != self._checksum:
                        # 同一バージョンでチェックサム不一致 = スキーマ漂流。
                        # マイグレーションを経ない書き換えは従来通り拒否する。
                        raise SchemaVersionError(
                            f"{self._db_path.name}: stored schema {row[0]}/{row[1][:12]} does not match"
                            f" code {self.SCHEMA_VERSION}/{self._checksum[:12]}"
                        )
                connection.execute("COMMIT")
            except BaseException:
                connection.execute("ROLLBACK")
                raise

    def verify_schema(self, connection: sqlite3.Connection) -> None:
        try:
            row = connection.execute(
                f"SELECT version, checksum FROM {self.SCHEMA_NAME}_schema WHERE id = 1"
            ).fetchone()
        except sqlite3.OperationalError as exc:
            raise SchemaVersionError(f"{self._db_path.name}: schema table missing") from exc
        if row is None or row[0] != self.SCHEMA_VERSION or row[1] != self._checksum:
            raise SchemaVersionError(f"{self._db_path.name}: schema version mismatch")

    def _connect_rw(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._db_path, isolation_level=None, timeout=10.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=5000")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    def _connect_ro(self) -> sqlite3.Connection:
        uri = f"file:{self._db_path}?mode=ro"
        connection = sqlite3.connect(uri, uri=True, isolation_level=None, timeout=10.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=5000")
        connection.execute("PRAGMA query_only=ON")
        return connection

    @contextmanager
    def write(self) -> Iterator[sqlite3.Connection]:
        if self._read_only:
            raise RuntimeError("repository opened read-only")
        connection = self._connect_rw()
        try:
            self.verify_schema(connection)
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
                connection.execute("COMMIT")
            except BaseException:
                connection.execute("ROLLBACK")
                raise
        finally:
            connection.close()

    @contextmanager
    def read(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect_ro() if self._read_only else self._connect_rw()
        try:
            self.verify_schema(connection)
            yield connection
        finally:
            connection.close()

    def exists(self) -> bool:
        return self._db_path.is_file()


__all__ = ["SQLiteRepository", "SchemaVersionError", "schema_checksum", "utc_now_iso"]
