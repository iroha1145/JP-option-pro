"""訪客アカウント: ストア往復・予約名・セッション・自選の主体分離。"""

from __future__ import annotations

import pytest

from app.repositories.app_store import AppStore
from app.services.accounts import (
    AccountError,
    AccountStore,
    hash_account_password,
    verify_account_password,
)


def test_password_hash_roundtrip_matches_us_format():
    encoded = hash_account_password("秘密のpassword")
    algorithm, iterations, _salt, _digest = encoded.split("$")
    # 米国版と同一パラメータ — 共有 accounts.db で相互検証できることの根拠。
    assert algorithm == "pbkdf2_sha256"
    assert iterations == "240000"
    assert verify_account_password("秘密のpassword", encoded)
    assert not verify_account_password("wrong", encoded)


def test_register_authenticate_and_session(tmp_path):
    store = AccountStore(tmp_path / "accounts.db")
    result = store.register("Taro", "pass-123")
    assert result.account.username == "Taro"
    # 大文字小文字は同一キー → 重複拒否。
    with pytest.raises(AccountError) as taken:
        store.register("taro", "other")
    assert taken.value.code == "username_taken"
    # 予約名はオーナー専用。
    with pytest.raises(AccountError) as reserved:
        store.register("Admin", "x")
    assert reserved.value.code == "username_reserved"
    session = store.authenticate("taro", "pass-123")
    account = store.resolve_session(session.token)
    assert account is not None and account.user_id == result.account.user_id
    store.revoke_session(session.token)
    assert store.resolve_session(session.token) is None
    with pytest.raises(AccountError):
        store.authenticate("taro", "wrong")


def test_session_expiry_uses_clock(tmp_path):
    now = [1_000_000.0]
    store = AccountStore(tmp_path / "accounts.db", clock=lambda: now[0])
    session = store.register("hana", "pw")
    assert store.resolve_session(session.token) is not None
    now[0] += 31 * 24 * 60 * 60  # 30日の期限を跨ぐ
    assert store.resolve_session(session.token) is None


def test_account_watchlist_is_isolated_per_user(tmp_path):
    store = AppStore(tmp_path / "app.db")
    store.initialize()
    # オーナーの自選と訪客の自選は別テーブル。
    store.add_to_watchlist("72030")
    assert store.account_watchlist("usr_a") == []
    assert store.account_add_to_watchlist("usr_a", "67580") is True
    assert store.account_add_to_watchlist("usr_a", "67580") is False  # 冪等
    store.account_add_to_watchlist("usr_b", "72030")
    codes_a = [row["canonical_code"] for row in store.account_watchlist("usr_a")]
    codes_b = [row["canonical_code"] for row in store.account_watchlist("usr_b")]
    assert codes_a == ["67580"]
    assert codes_b == ["72030"]
    assert store.account_update_watchlist_item("usr_a", "67580", marked_important=True)
    assert store.account_watchlist("usr_a")[0]["marked_important"] == 1
    assert store.account_remove_from_watchlist("usr_a", "67580")
    assert store.account_watchlist("usr_a") == []
    # オーナー側は無傷。
    assert [row["canonical_code"] for row in store.watchlist()] == ["72030"]


def test_app_store_v1_migrates_to_v2(tmp_path):
    import sqlite3

    db_path = tmp_path / "app.db"
    store = AppStore(db_path)
    store.initialize()
    with sqlite3.connect(db_path) as connection:
        connection.execute("DROP TABLE account_watchlist")
        connection.execute(
            "UPDATE jp_app_schema SET version='jp-app-v1', checksum='legacy' WHERE id=1"
        )
        connection.commit()
    migrated = AppStore(db_path)
    migrated.initialize()
    assert migrated.account_watchlist("usr_x") == []  # 表が復元されている
