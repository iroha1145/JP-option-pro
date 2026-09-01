"""jp-core.db の冪等性・カレンダー・チェックポイント検証。"""

from app.repositories.core import CoreRepository


def _repo(tmp_path) -> CoreRepository:
    repo = CoreRepository(tmp_path / "jp-core.db")
    repo.initialize()
    return repo


def test_daily_bar_upsert_is_idempotent(tmp_path):
    repo = _repo(tmp_path)
    bar = {
        "canonical_code": "72030", "trade_date": "2026-07-31",
        "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5,
        "turnover_value": 100.0,
    }
    assert repo.upsert_daily_bars([bar]) == 1
    assert repo.upsert_daily_bars([bar]) == 1  # 再実行してもエラーなし
    bars = repo.bars_for_code("72030")
    assert len(bars) == 1 and bars[0]["close"] == 1.5
    # 公式訂正は受け入れる（同キー上書き）
    repo.upsert_daily_bars([{**bar, "close": 1.6}])
    assert repo.bars_for_code("72030")[0]["close"] == 1.6


def test_master_replace_deactivates_missing_codes(tmp_path):
    repo = _repo(tmp_path)
    day1 = [
        {"canonical_code": "72030", "name_ja": "トヨタ自動車", "market_code": "0111"},
        {"canonical_code": "99840", "name_ja": "ソフトバンクグループ", "market_code": "0111"},
    ]
    repo.replace_security_master(day1, as_of_date="2026-07-30")
    day2 = [{"canonical_code": "72030", "name_ja": "トヨタ自動車", "market_code": "0111"}]
    outcome = repo.replace_security_master(day2, as_of_date="2026-07-31")
    assert outcome["deactivated"] == 1
    gone = repo.get_security("99840")
    assert gone["active"] == 0 and gone["delisted_date"] == "2026-07-31"
    # 再上場（マスタ復帰）で active に戻る
    repo.replace_security_master(day1, as_of_date="2026-08-01")
    assert repo.get_security("99840")["active"] == 1


def test_trading_calendar_half_day_counts_as_trading(tmp_path):
    repo = _repo(tmp_path)
    repo.upsert_trading_days(
        [
            {"calendar_date": "2026-01-02", "holiday_division": "0"},
            {"calendar_date": "2026-01-05", "holiday_division": "1"},
            {"calendar_date": "2026-01-06", "holiday_division": "2"},  # 半日立会
            {"calendar_date": "2026-01-07", "holiday_division": "3"},  # 祝日取引=現物休場
        ]
    )
    assert repo.trading_days_between("2026-01-01", "2026-01-07") == ["2026-01-05", "2026-01-06"]
    assert repo.latest_trading_day("2026-01-07") == "2026-01-06"
    assert repo.next_trading_day("2026-01-05") == "2026-01-06"
    assert repo.is_trading_day("2026-01-07") is False
    assert repo.is_trading_day("2026-12-31") is None  # 未知の日付は不明のまま


def test_sync_state_checkpoint_merge_and_error(tmp_path):
    repo = _repo(tmp_path)
    repo.record_sync_success("daily_prices", checkpoint={"last_synced_date": "2026-07-30"}, rows_total=10, data_through="2026-07-30")
    repo.record_sync_success("daily_prices", checkpoint={"bulk_done": ["a.csv"]})
    state = repo.sync_state("daily_prices")
    # マージされる（上書きで消えない）
    assert state["checkpoint"]["last_synced_date"] == "2026-07-30"
    assert state["checkpoint"]["bulk_done"] == ["a.csv"]
    assert state["last_error_code"] is None
    repo.record_sync_error("daily_prices", "jquants_timeout")
    state = repo.sync_state("daily_prices")
    assert state["last_error_code"] == "jquants_timeout"
    assert state["last_success_at"] is not None  # 失敗しても成功履歴は残る


def test_read_only_repository_cannot_write(tmp_path):
    writer = _repo(tmp_path)
    writer.upsert_trading_days([{"calendar_date": "2026-01-05", "holiday_division": "1"}])
    reader = CoreRepository(tmp_path / "jp-core.db", read_only=True)
    assert reader.is_trading_day("2026-01-05") is True
    try:
        reader.upsert_trading_days([{"calendar_date": "2026-01-06", "holiday_division": "1"}])
        raised = False
    except RuntimeError:
        raised = True
    assert raised


def test_earnings_replace_semantics(tmp_path):
    repo = _repo(tmp_path)
    repo.replace_earnings_announcements(
        [{"canonical_code": "72030", "fiscal_quarter": "第１四半期", "announcement_date": "2026-08-05"}]
    )
    repo.replace_earnings_announcements(
        [{"canonical_code": "67580", "fiscal_quarter": "第１四半期", "announcement_date": "2026-08-06"}]
    )
    rows = repo.earnings_between("2026-08-01", "2026-08-31")
    assert [row["canonical_code"] for row in rows] == ["67580"]  # 全量置換
    # 空入力は既存を消さない（空の 200 がカレンダーを消す経路）
    repo.replace_earnings_announcements([])
    rows = repo.earnings_between("2026-08-01", "2026-08-31")
    assert [row["canonical_code"] for row in rows] == ["67580"]


def test_screener_query_null_sorts_last(tmp_path):
    repo = _repo(tmp_path)
    repo.replace_screener_rows(
        [
            {"canonical_code": "A0010", "trade_date": "2026-07-31", "rs_topix_63d": 0.10, "close": 100},
            {"canonical_code": "B0020", "trade_date": "2026-07-31", "rs_topix_63d": None, "close": 200},
            {"canonical_code": "C0030", "trade_date": "2026-07-31", "rs_topix_63d": 0.30, "close": 300},
        ]
    )
    rows, total = repo.screener_query(
        where_sql="1=1", params=[],
        order_sql="rs_topix_63d IS NULL, rs_topix_63d DESC, canonical_code ASC",
        limit=10, offset=0,
    )
    assert total == 3
    assert [row["canonical_code"] for row in rows] == ["C0030", "A0010", "B0020"]  # NULL は末尾


def _snapshot_row(code: str, as_of: str) -> dict:
    from app.repositories.core import CoreRepository as _C

    row = {column: 0 for column in _C._SNAPSHOT_COLUMNS}
    row.update(
        canonical_code=code, as_of_date=as_of, primary_state="no_signal",
        flags_json="[]", components_json="{}", algorithm_version="test",
    )
    return row


def test_republish_with_fewer_codes_leaves_no_ghost_snapshot_rows(tmp_path):
    repo = _repo(tmp_path)
    day = "2026-07-31"
    repo.publish_short_behavior_day(
        [_snapshot_row("1", day), _snapshot_row("2", day), _snapshot_row("3", day)],
        [], as_of_date=day, run_id="r1", algorithm_version="test",
    )
    assert len(repo.short_behavior_state_map(day)) == 3
    # Re-publish the SAME day with a smaller universe (e.g. correction rebuild).
    repo.publish_short_behavior_day(
        [_snapshot_row("1", day)], [], as_of_date=day, run_id="r2", algorithm_version="test",
    )
    remaining = repo.short_behavior_state_map(day)
    assert set(remaining) == {"1"}  # no ghosts from the first build
    run = repo.latest_short_monitor_run(day)
    assert run["row_count"] == 1  # marker matches the table


def test_empty_replace_does_not_wipe_screener_or_strength(tmp_path):
    repo = _repo(tmp_path)
    assert repo.replace_screener_rows([{"canonical_code": "72030", "trade_date": "2026-07-31"}]) == 1
    assert repo.replace_screener_rows([]) == 0  # empty input must not wipe
    rows, total = repo.screener_query(where_sql="1=1", params=[], order_sql="canonical_code", limit=10, offset=0)
    assert total == 1

    assert repo.replace_strength_rows(
        [{"canonical_code": "72030", "trade_date": "2026-07-31"}],
        trade_date="2026-07-31", regime={"score": 50.0},
    ) == 1
    assert repo.replace_strength_rows([], trade_date="2026-08-01", regime={"score": 10.0}) == 0
    assert len(repo.strength_rows_all()) == 1  # kept last good snapshot
    assert repo.strength_meta()["trade_date"] == "2026-07-31"  # meta not clobbered
