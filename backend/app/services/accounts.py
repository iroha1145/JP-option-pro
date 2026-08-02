"""訪客アカウント — 米国版 option-pro の accounts.db と**同一スキーマ**の移植。

「数据共通」の要: 本番では ``ACCOUNTS_DB_PATH`` を米国版デプロイの
accounts.db に向け、同じユーザー名・パスワードが両サイトで通用する。
そのためスキーマ・PBKDF2 パラメータ・セッショントークンの持ち方
（sha256 ダイジェスト保存）は米国版と厳密に一致させ、両プロセスが
同じファイルへ CREATE TABLE IF NOT EXISTS しても衝突しない。

役割はあくまで訪客の身元確認。オーナー権限は app.access の別セッション
（APP_PASSWORD_HASH）にのみ由来し、この店は一切の権限を付与しない。
日本株の自選リストは jp-app.db 側（AppStore.account_watchlist）に保存し、
共有 accounts.db の account_watchlist（米国株ティッカー）は触らない。
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import threading
import time
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.access import _b64decode, _b64encode

_PBKDF2_ITERATIONS = 240_000
_PASSWORD_HASH_LENGTH = 32

RESERVED_USERNAMES = frozenset({"admin", "administrator", "root", "owner", "optix"})

USERNAME_MAX_LENGTH = 32
PASSWORD_MAX_LENGTH = 256
SESSION_SECONDS = 30 * 24 * 60 * 60

_DISALLOWED_USERNAME_CHARS = re.compile(r"[\s\x00-\x1f\x7f]")

#: 米国版 services/accounts.py と同一の DDL。片方が先に作っていても
#: IF NOT EXISTS で素通りする。account_watchlist は互換のため定義だけ持つ。
_SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    user_id TEXT PRIMARY KEY,
    username TEXT NOT NULL,
    username_key TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_login_at TEXT
);
CREATE TABLE IF NOT EXISTS account_sessions (
    token_sha256 TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES accounts(user_id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    expires_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_account_sessions_user
    ON account_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_account_sessions_expiry
    ON account_sessions(expires_at);
CREATE TABLE IF NOT EXISTS account_watchlist (
    user_id TEXT NOT NULL REFERENCES accounts(user_id) ON DELETE CASCADE,
    ticker TEXT NOT NULL,
    position INTEGER NOT NULL,
    added_at TEXT NOT NULL,
    PRIMARY KEY (user_id, ticker)
);
CREATE INDEX IF NOT EXISTS idx_account_watchlist_order
    ON account_watchlist(user_id, position);
"""


class AccountError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Account:
    user_id: str
    username: str
    created_at: str


@dataclass(frozen=True)
class SessionResult:
    token: str
    expires_at: float
    account: Account


def hash_account_password(password: str, *, salt: bytes | None = None) -> str:
    validate_password(password)
    resolved_salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), resolved_salt,
        _PBKDF2_ITERATIONS, dklen=_PASSWORD_HASH_LENGTH,
    )
    return "$".join(
        ("pbkdf2_sha256", str(_PBKDF2_ITERATIONS), _b64encode(resolved_salt), _b64encode(digest))
    )


def verify_account_password(password: str, encoded_hash: str) -> bool:
    try:
        algorithm, raw_iterations, raw_salt, raw_digest = encoded_hash.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        iterations = int(raw_iterations)
        salt = _b64decode(raw_salt)
        expected = _b64decode(raw_digest)
        if len(salt) < 16 or len(expected) != _PASSWORD_HASH_LENGTH:
            return False
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, iterations, dklen=len(expected)
        )
    except Exception:
        return False
    return hmac.compare_digest(actual, expected)


def validate_password(password: str) -> str:
    if not password:
        raise AccountError("password_required")
    if len(password) > PASSWORD_MAX_LENGTH:
        raise AccountError("password_too_long")
    if any(character in password for character in ("\x00", "\r", "\n")):
        raise AccountError("password_invalid_characters")
    return password


def normalize_username(username: str) -> tuple[str, str]:
    display = unicodedata.normalize("NFKC", str(username or "")).strip()
    if not display:
        raise AccountError("username_required")
    if len(display) > USERNAME_MAX_LENGTH:
        raise AccountError("username_too_long")
    if _DISALLOWED_USERNAME_CHARS.search(display):
        raise AccountError("username_invalid_characters")
    key = display.casefold()
    if key in RESERVED_USERNAMES:
        raise AccountError("username_reserved")
    return display, key


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class AccountStore:
    """共有 accounts.db 上のアカウントとセッション（米国版互換）。"""

    def __init__(self, path: str | Path, *, clock: Any = time.time, max_accounts: int = 2000) -> None:
        self.path = Path(path)
        self._clock = clock
        self._max_accounts = int(max_accounts)
        self._lock = threading.Lock()
        self._initialized = False

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=10.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=10000")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def initialize(self) -> None:
        if self._initialized:
            return
        with self._lock:
            if self._initialized:
                return
            with self._connect() as connection:
                connection.executescript(_SCHEMA)
                connection.commit()
            self._initialized = True

    # ---------------- accounts ----------------

    def register(self, username: str, password: str) -> SessionResult:
        display, key = normalize_username(username)
        password_hash = hash_account_password(password)
        self.initialize()
        now_iso = _utcnow_iso()
        user_id = f"usr_{uuid.uuid4().hex}"
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            total = int(connection.execute("SELECT COUNT(*) FROM accounts").fetchone()[0])
            if total >= self._max_accounts:
                connection.rollback()
                raise AccountError("registration_closed")
            existing = connection.execute(
                "SELECT 1 FROM accounts WHERE username_key=?", (key,)
            ).fetchone()
            if existing is not None:
                connection.rollback()
                raise AccountError("username_taken")
            connection.execute(
                "INSERT INTO accounts (user_id, username, username_key, password_hash, created_at)"
                " VALUES (?,?,?,?,?)",
                (user_id, display, key, password_hash, now_iso),
            )
            connection.commit()
        account = Account(user_id=user_id, username=display, created_at=now_iso)
        return self._issue_session(account)

    def authenticate(self, username: str, password: str) -> SessionResult:
        try:
            _display, key = normalize_username(username)
        except AccountError:
            raise AccountError("invalid_credentials") from None
        self.initialize()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT user_id, username, password_hash, created_at FROM accounts WHERE username_key=?",
                (key,),
            ).fetchone()
        if row is None:
            # 実在しないユーザーが速く返らないよう同等時間を費やす。
            verify_account_password(password, hash_account_password("placeholder"))
            raise AccountError("invalid_credentials")
        if not verify_account_password(password, str(row["password_hash"])):
            raise AccountError("invalid_credentials")
        account = Account(
            user_id=str(row["user_id"]), username=str(row["username"]),
            created_at=str(row["created_at"]),
        )
        with self._connect() as connection:
            connection.execute(
                "UPDATE accounts SET last_login_at=? WHERE user_id=?",
                (_utcnow_iso(), account.user_id),
            )
            connection.commit()
        return self._issue_session(account)

    def account_count(self) -> int:
        self.initialize()
        with self._connect() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM accounts").fetchone()[0])

    # ---------------- sessions ----------------

    def _issue_session(self, account: Account) -> SessionResult:
        token = secrets.token_urlsafe(32)
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        expires_at = float(self._clock()) + SESSION_SECONDS
        with self._connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO account_sessions (token_sha256, user_id, created_at, expires_at)"
                " VALUES (?,?,?,?)",
                (digest, account.user_id, _utcnow_iso(), expires_at),
            )
            connection.execute(
                "DELETE FROM account_sessions WHERE expires_at<=?", (float(self._clock()),)
            )
            connection.commit()
        return SessionResult(token=token, expires_at=expires_at, account=account)

    def resolve_session(self, token: str) -> Account | None:
        if not token:
            return None
        self.initialize()
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        now = float(self._clock())
        with self._connect() as connection:
            row = connection.execute(
                """SELECT a.user_id, a.username, a.created_at
                     FROM account_sessions AS s JOIN accounts AS a ON a.user_id=s.user_id
                    WHERE s.token_sha256=? AND s.expires_at>?""",
                (digest, now),
            ).fetchone()
        if row is None:
            return None
        return Account(
            user_id=str(row["user_id"]), username=str(row["username"]),
            created_at=str(row["created_at"]),
        )

    def revoke_session(self, token: str) -> None:
        if not token:
            return
        self.initialize()
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        with self._connect() as connection:
            connection.execute("DELETE FROM account_sessions WHERE token_sha256=?", (digest,))
            connection.commit()


_store: AccountStore | None = None
_store_lock = threading.Lock()


def accounts_db_path() -> Path:
    """共有パス優先: ACCOUNTS_DB_PATH（米国版と共通のファイル）→ DATA_DIR/accounts.db。"""

    raw = os.environ.get("ACCOUNTS_DB_PATH", "").strip()
    if raw:
        return Path(raw)
    from app.data_paths import get_data_paths

    return get_data_paths().root / "accounts.db"


def get_account_store() -> AccountStore:
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = AccountStore(accounts_db_path())
    return _store


def set_account_store(store: AccountStore | None) -> None:
    """テスト継ぎ目。"""

    global _store
    with _store_lock:
        _store = store


__all__ = [
    "Account",
    "AccountError",
    "AccountStore",
    "RESERVED_USERNAMES",
    "SESSION_SECONDS",
    "SessionResult",
    "accounts_db_path",
    "get_account_store",
    "hash_account_password",
    "normalize_username",
    "set_account_store",
    "verify_account_password",
]
