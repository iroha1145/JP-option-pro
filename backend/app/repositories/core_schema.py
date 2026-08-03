"""jp-core.db DDL — the worker-owned Japanese market datastore.

Fresh schema, no lineage from the US project. Completed trading days are
treated as immutable; official revisions overwrite through idempotent
upserts that keep ``ingested_at`` as the revision stamp.
"""

from __future__ import annotations

CORE_SCHEMA_VERSION = "jp-core-v4"

# v3: 全市場スナップショット照会（決算カレンダーの終値/前日比マップ等）を
# カバリングインデックスで賄う。272MB の WITHOUT ROWID 主表への 4千回の
# ランダム回表はコールドキャッシュで ~2 秒かかる — 索引だけで完結させる。
_QUOTE_INDEX_DDL: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS idx_daily_bars_date_quote ON daily_bars(trade_date, canonical_code, close, adj_close)",
)

# -- 強度スキャン断面（v2 追加）。米国版 Strength Radar の日本株移植:
#    夜間バッチが銘柄内在評価（intrinsic）を全量計算して保存し、API は
#    profile/market の重ね掛けだけを要求時に行う。details_json には
#    因子ファミリ内訳・欠損監査・構造タグの素材を丸ごと保存する。
_STRENGTH_DDL: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS strength_rows (
        canonical_code TEXT PRIMARY KEY,
        trade_date TEXT NOT NULL,
        intrinsic_score REAL,
        confidence REAL,
        score_short REAL,
        score_mid REAL,
        score_long REAL,
        trend_score REAL,
        breakout_quality_score REAL,
        price_action_score REAL,
        global_rank_percentile REAL,
        sector_rank_percentile REAL,
        close REAL,
        change_pct REAL,
        atr_pct REAL,
        avg_turnover_20d REAL,
        turnover_ratio REAL,
        ath_proximity REAL,
        drawdown_63d_pct REAL,
        ma_alignment_pct REAL,
        rs_topix_63d REAL,
        market_code TEXT,
        sector33_code TEXT,
        details_json TEXT NOT NULL DEFAULT '{}',
        built_at TEXT NOT NULL
    ) WITHOUT ROWID
    """,
    "CREATE INDEX IF NOT EXISTS idx_strength_score ON strength_rows(intrinsic_score)",
    "CREATE INDEX IF NOT EXISTS idx_strength_sector ON strength_rows(sector33_code)",
    """
    CREATE TABLE IF NOT EXISTS strength_meta (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        trade_date TEXT NOT NULL,
        regime_json TEXT NOT NULL DEFAULT '{}',
        universe_count INTEGER NOT NULL DEFAULT 0,
        built_at TEXT NOT NULL
    )
    """,
)

CORE_DDL: tuple[str, ...] = (
    # -- 上場銘柄マスタ（現在ビュー） ---------------------------------------
    """
    CREATE TABLE IF NOT EXISTS securities (
        canonical_code TEXT PRIMARY KEY,
        display_code TEXT NOT NULL,
        name_ja TEXT,
        name_en TEXT,
        sector17_code TEXT,
        sector17_name TEXT,
        sector33_code TEXT,
        sector33_name TEXT,
        scale_category TEXT,
        market_code TEXT,
        market_name TEXT,
        margin_code TEXT,
        margin_name TEXT,
        product_category TEXT,
        as_of_date TEXT,
        first_seen_date TEXT,
        delisted_date TEXT,
        active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
        updated_at TEXT NOT NULL
    ) WITHOUT ROWID
    """,
    "CREATE INDEX IF NOT EXISTS idx_securities_market ON securities(market_code, active)",
    "CREATE INDEX IF NOT EXISTS idx_securities_sector33 ON securities(sector33_code, active)",
    "CREATE INDEX IF NOT EXISTS idx_securities_display ON securities(display_code)",
    # -- 取引カレンダー ------------------------------------------------------
    """
    CREATE TABLE IF NOT EXISTS trading_calendar (
        calendar_date TEXT PRIMARY KEY,
        holiday_division TEXT NOT NULL
    ) WITHOUT ROWID
    """,
    # -- 株価日足（無調整 + 調整済み） ---------------------------------------
    """
    CREATE TABLE IF NOT EXISTS daily_bars (
        canonical_code TEXT NOT NULL,
        trade_date TEXT NOT NULL,
        open REAL, high REAL, low REAL, close REAL,
        upper_limit INTEGER, lower_limit INTEGER,
        volume REAL, turnover_value REAL,
        adjustment_factor REAL,
        adj_open REAL, adj_high REAL, adj_low REAL, adj_close REAL, adj_volume REAL,
        ingested_at TEXT NOT NULL,
        PRIMARY KEY (canonical_code, trade_date)
    ) WITHOUT ROWID
    """,
    "CREATE INDEX IF NOT EXISTS idx_daily_bars_date ON daily_bars(trade_date)",
    # -- 指数日足 -------------------------------------------------------------
    """
    CREATE TABLE IF NOT EXISTS index_bars (
        index_code TEXT NOT NULL,
        trade_date TEXT NOT NULL,
        open REAL, high REAL, low REAL, close REAL,
        ingested_at TEXT NOT NULL,
        PRIMARY KEY (index_code, trade_date)
    ) WITHOUT ROWID
    """,
    "CREATE INDEX IF NOT EXISTS idx_index_bars_date ON index_bars(trade_date)",
    # -- 財務サマリー（開示単位で不変、訂正は新しい開示番号で届く） -----------
    """
    CREATE TABLE IF NOT EXISTS financial_summaries (
        canonical_code TEXT NOT NULL,
        disclosed_date TEXT NOT NULL,
        disclosure_number TEXT NOT NULL DEFAULT '',
        disclosed_time TEXT,
        type_of_document TEXT,
        period_type TEXT,
        period_start TEXT,
        period_end TEXT,
        fiscal_year_start TEXT,
        fiscal_year_end TEXT,
        next_fiscal_year_start TEXT,
        next_fiscal_year_end TEXT,
        sales REAL, operating_profit REAL, ordinary_profit REAL, net_profit REAL,
        eps REAL, total_assets REAL, equity REAL, equity_ratio REAL, bps REAL,
        forecast_sales_2q REAL, forecast_operating_profit_2q REAL,
        forecast_ordinary_profit_2q REAL, forecast_net_profit_2q REAL, forecast_eps_2q REAL,
        forecast_sales REAL, forecast_operating_profit REAL,
        forecast_ordinary_profit REAL, forecast_net_profit REAL, forecast_eps REAL,
        next_forecast_sales REAL, next_forecast_operating_profit REAL,
        next_forecast_ordinary_profit REAL, next_forecast_net_profit REAL, next_forecast_eps REAL,
        dividend_annual REAL, forecast_dividend_annual REAL, next_forecast_dividend_annual REAL,
        payout_ratio_annual REAL,
        material_change_subsidiaries TEXT,
        change_by_accounting_standard TEXT,
        change_other_than_accounting_standard TEXT,
        change_accounting_estimate TEXT,
        retrospective_restatement TEXT,
        shares_outstanding_fy REAL, treasury_shares_fy REAL, average_shares REAL,
        nc_sales REAL, nc_operating_profit REAL, nc_ordinary_profit REAL,
        nc_net_profit REAL, nc_eps REAL,
        ingested_at TEXT NOT NULL,
        PRIMARY KEY (canonical_code, disclosed_date, disclosure_number)
    ) WITHOUT ROWID
    """,
    "CREATE INDEX IF NOT EXISTS idx_fins_disclosed ON financial_summaries(disclosed_date)",
    # -- 決算発表予定（同期毎に全量置換するローリングウィンドウ） -------------
    """
    CREATE TABLE IF NOT EXISTS earnings_announcements (
        canonical_code TEXT NOT NULL,
        fiscal_year_end TEXT NOT NULL DEFAULT '',
        fiscal_quarter TEXT NOT NULL DEFAULT '',
        announcement_date TEXT NOT NULL DEFAULT '',
        company_name TEXT,
        sector_name TEXT,
        section TEXT,
        synced_at TEXT NOT NULL,
        PRIMARY KEY (canonical_code, fiscal_year_end, fiscal_quarter)
    ) WITHOUT ROWID
    """,
    "CREATE INDEX IF NOT EXISTS idx_earnings_date ON earnings_announcements(announcement_date)",
    # -- 信用取引週末残高 ------------------------------------------------------
    """
    CREATE TABLE IF NOT EXISTS margin_interest (
        canonical_code TEXT NOT NULL,
        application_date TEXT NOT NULL,
        short_total REAL, long_total REAL,
        short_negotiable REAL, long_negotiable REAL,
        short_standardized REAL, long_standardized REAL,
        issue_type TEXT,
        ingested_at TEXT NOT NULL,
        PRIMARY KEY (canonical_code, application_date)
    ) WITHOUT ROWID
    """,
    "CREATE INDEX IF NOT EXISTS idx_margin_interest_date ON margin_interest(application_date)",
    # -- 日々公表信用取引残高（訂正は同じ申込日で新しい公表日の行になる） -------
    """
    CREATE TABLE IF NOT EXISTS margin_alerts (
        canonical_code TEXT NOT NULL,
        published_date TEXT NOT NULL DEFAULT '',
        application_date TEXT NOT NULL DEFAULT '',
        short_outstanding REAL, long_outstanding REAL, short_long_ratio REAL,
        short_outstanding_change REAL, long_outstanding_change REAL,
        short_outstanding_listed_ratio REAL, long_outstanding_listed_ratio REAL,
        short_negotiable REAL, short_standardized REAL,
        long_negotiable REAL, long_standardized REAL,
        tse_regulation_class TEXT,
        publish_reason TEXT,
        ingested_at TEXT NOT NULL,
        PRIMARY KEY (canonical_code, published_date, application_date)
    ) WITHOUT ROWID
    """,
    "CREATE INDEX IF NOT EXISTS idx_margin_alerts_app ON margin_alerts(application_date)",
    # -- 業種別空売り比率 ------------------------------------------------------
    """
    CREATE TABLE IF NOT EXISTS short_sale_ratios (
        sector33_code TEXT NOT NULL,
        trade_date TEXT NOT NULL,
        selling_ex_short_value REAL,
        short_with_restriction_value REAL,
        short_without_restriction_value REAL,
        ingested_at TEXT NOT NULL,
        PRIMARY KEY (sector33_code, trade_date)
    ) WITHOUT ROWID
    """,
    "CREATE INDEX IF NOT EXISTS idx_short_ratio_date ON short_sale_ratios(trade_date)",
    # -- 空売り残高報告 --------------------------------------------------------
    """
    CREATE TABLE IF NOT EXISTS short_positions (
        canonical_code TEXT NOT NULL,
        disclosed_date TEXT NOT NULL,
        calculated_date TEXT NOT NULL,
        holder_name TEXT NOT NULL DEFAULT '',
        investment_fund_name TEXT,
        short_position_ratio REAL,
        short_position_shares REAL,
        short_position_units REAL,
        previous_report_date TEXT,
        previous_ratio REAL,
        notes TEXT,
        ingested_at TEXT NOT NULL,
        PRIMARY KEY (canonical_code, disclosed_date, calculated_date, holder_name)
    ) WITHOUT ROWID
    """,
    "CREATE INDEX IF NOT EXISTS idx_short_positions_code ON short_positions(canonical_code, calculated_date)",
    # -- レーダーイベント（日足ライフサイクル） --------------------------------
    """
    CREATE TABLE IF NOT EXISTS radar_events (
        event_id TEXT PRIMARY KEY,
        canonical_code TEXT NOT NULL,
        signal_type TEXT NOT NULL,
        state TEXT NOT NULL,
        discovered_date TEXT NOT NULL,
        pivot_price REAL,
        trigger_price REAL,
        state_changed_date TEXT NOT NULL,
        last_scanned_date TEXT NOT NULL,
        alert_priority REAL,
        scores_json TEXT NOT NULL DEFAULT '{}',
        features_json TEXT NOT NULL DEFAULT '{}',
        transitions_json TEXT NOT NULL DEFAULT '[]',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_radar_state ON radar_events(state, last_scanned_date)",
    "CREATE INDEX IF NOT EXISTS idx_radar_code ON radar_events(canonical_code, discovered_date)",
    "CREATE INDEX IF NOT EXISTS idx_radar_priority ON radar_events(last_scanned_date, alert_priority)",
    # -- スクリーナー断面（毎営業日引け後に全量再構築） -------------------------
    """
    CREATE TABLE IF NOT EXISTS screener_rows (
        canonical_code TEXT PRIMARY KEY,
        trade_date TEXT NOT NULL,
        market_code TEXT,
        sector33_code TEXT,
        close REAL,
        turnover_value REAL,
        avg_turnover_20d REAL,
        turnover_ratio REAL,
        return_1d REAL,
        return_5d REAL,
        return_20d REAL,
        return_63d REAL,
        pct_from_high_252 REAL,
        ma25_gap_pct REAL,
        ma75_gap_pct REAL,
        ma200_gap_pct REAL,
        ma_alignment INTEGER,
        rs_topix_63d REAL,
        rs_sector_20d REAL,
        rs_sector_63d REAL,
        regulation_level TEXT,
        regulation_severity INTEGER,
        volatility_contraction REAL,
        drawdown_63d REAL,
        overheat_atr_multiple REAL,
        listed_days INTEGER,
        data_days INTEGER,
        margin_long_short_ratio REAL,
        metrics_json TEXT NOT NULL DEFAULT '{}',
        updated_at TEXT NOT NULL
    ) WITHOUT ROWID
    """,
    "CREATE INDEX IF NOT EXISTS idx_screener_market ON screener_rows(market_code)",
    "CREATE INDEX IF NOT EXISTS idx_screener_sector ON screener_rows(sector33_code)",
    # -- 同期チェックポイント --------------------------------------------------
    """
    CREATE TABLE IF NOT EXISTS sync_state (
        dataset TEXT PRIMARY KEY,
        last_success_at TEXT,
        last_attempt_at TEXT,
        last_error_code TEXT,
        last_error_at TEXT,
        checkpoint_json TEXT NOT NULL DEFAULT '{}',
        rows_total INTEGER,
        data_through TEXT
    ) WITHOUT ROWID
    """,
    *_STRENGTH_DDL,
    *_QUOTE_INDEX_DDL,
)

#: v4: 業種相対の 20 日/63 日分離 + 信用規制状態。
#: 既存行は NULL のまま（= 欠損）。夜間バッチが翌営業日に埋め直す。
#: 20 日の値を 63 日の名前で保存していた過去分は、意味が違うので移し替えない
#: —— 移すと「昔から 63 日で測っていた」という嘘の履歴ができる。
_RS_SECTOR_SPLIT_DDL: tuple[str, ...] = (
    "ALTER TABLE screener_rows ADD COLUMN rs_sector_20d REAL",
    "ALTER TABLE screener_rows ADD COLUMN regulation_level TEXT",
    "ALTER TABLE screener_rows ADD COLUMN regulation_severity INTEGER",
    # 旧 rs_sector_63d の中身は実際には 20 日だったので、名前どおりの値が
    # 入り直すまで区別できるよう一度 NULL に戻す（誤った値を残さない）。
    "UPDATE screener_rows SET rs_sector_63d = NULL",
)

#: 前方マイグレーション連鎖: v1 → v2（強度断面）→ v3（クオート索引）
#: → v4（業種相対の周期分離・信用規制）。
CORE_MIGRATIONS: dict[str, tuple[tuple[str, ...], str]] = {
    "jp-core-v1": (_STRENGTH_DDL, "jp-core-v2"),
    "jp-core-v2": (_QUOTE_INDEX_DDL, "jp-core-v3"),
    "jp-core-v3": (_RS_SECTOR_SPLIT_DDL, CORE_SCHEMA_VERSION),
}

__all__ = ["CORE_DDL", "CORE_MIGRATIONS", "CORE_SCHEMA_VERSION"]
