"""jp-core.db DDL — the worker-owned Japanese market datastore.

Fresh schema, no lineage from the US project. Completed trading days are
treated as immutable; official revisions overwrite through idempotent
upserts that keep ``ingested_at`` as the revision stamp.
"""

from __future__ import annotations

CORE_SCHEMA_VERSION = "jp-core-v7"

# -- 機関空売り行動モニター（v6 追加）--------------------------------------
#
# `short_positions` は J-Quants の生取り込みのまま残し、ここから **導出** する。
# 導出物は algorithm_version 付きで、いつでも作り直せる。
#
# 命名の約束: 公開開示に達した分しか見えないので、どこにも
# `total_short_*` とは書かない。`visible` / `reported` を必ず付ける。
_SHORT_MONITOR_DDL: tuple[str, ...] = (
    # 機関の法的実体。名前が似ているだけでは統合しない（統合は alias 表を通す）。
    """
    CREATE TABLE IF NOT EXISTS institution_entities (
        legal_id TEXT PRIMARY KEY,
        display_name TEXT NOT NULL,
        normalized_name TEXT NOT NULL,
        group_id TEXT,
        group_name TEXT,
        country_hint TEXT,
        first_seen_date TEXT,
        last_seen_date TEXT,
        report_count INTEGER NOT NULL DEFAULT 0,
        updated_at TEXT NOT NULL
    ) WITHOUT ROWID
    """,
    "CREATE INDEX IF NOT EXISTS idx_institution_entities_group ON institution_entities(group_id)",
    # 生の表記 → 法的実体。`confidence` は「この対応づけをどれだけ信じてよいか」。
    # curated = 人手の別名表、normalized = 正規化後の完全一致、
    # unmapped = 初出（統合せず単独の実体として立てる）。
    """
    CREATE TABLE IF NOT EXISTS institution_aliases (
        raw_name TEXT PRIMARY KEY,
        legal_id TEXT NOT NULL,
        match_kind TEXT NOT NULL,
        confidence REAL NOT NULL,
        raw_address TEXT,
        manager_name TEXT,
        updated_at TEXT NOT NULL
    ) WITHOUT ROWID
    """,
    "CREATE INDEX IF NOT EXISTS idx_institution_aliases_legal ON institution_aliases(legal_id)",
    # 正規化済みイベント。1 本の報告 = 1 行。
    """
    CREATE TABLE IF NOT EXISTS short_position_events (
        event_id TEXT PRIMARY KEY,
        canonical_code TEXT NOT NULL,
        legal_id TEXT NOT NULL,
        group_id TEXT,
        raw_holder_name TEXT NOT NULL,
        position_date TEXT NOT NULL,
        published_date TEXT NOT NULL,
        effective_trade_date TEXT NOT NULL,
        short_ratio REAL,
        short_shares REAL,
        previous_ratio REAL,
        previous_report_date TEXT,
        ratio_delta REAL,
        shares_delta REAL,
        event_type TEXT NOT NULL,
        visibility_status TEXT NOT NULL,
        correction_status TEXT NOT NULL DEFAULT 'original',
        is_hedge_disclosed INTEGER NOT NULL DEFAULT 0,
        mapping_confidence REAL,
        algorithm_version TEXT NOT NULL,
        ingested_at TEXT NOT NULL
    ) WITHOUT ROWID
    """,
    "CREATE INDEX IF NOT EXISTS idx_spe_code_pub ON short_position_events(canonical_code, published_date)",
    "CREATE INDEX IF NOT EXISTS idx_spe_effective ON short_position_events(effective_trade_date, canonical_code)",
    "CREATE INDEX IF NOT EXISTS idx_spe_legal ON short_position_events(legal_id, published_date)",
    # 「最後に公開された状態」。**その日の実仓位ではない。**
    """
    CREATE TABLE IF NOT EXISTS short_position_last_known (
        canonical_code TEXT NOT NULL,
        legal_id TEXT NOT NULL,
        group_id TEXT,
        last_reported_ratio REAL,
        last_reported_shares REAL,
        last_position_date TEXT,
        last_published_date TEXT,
        visibility_status TEXT NOT NULL,
        exact_position_known INTEGER NOT NULL DEFAULT 1,
        -- 報告義務中の表示のまま古くなった（閾値割れとは別）
        stale_reporting INTEGER NOT NULL DEFAULT 0,
        state_age_trading_days INTEGER,
        is_hedge_disclosed INTEGER NOT NULL DEFAULT 0,
        mapping_confidence REAL,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (canonical_code, legal_id)
    ) WITHOUT ROWID
    """,
    "CREATE INDEX IF NOT EXISTS idx_splk_code ON short_position_last_known(canonical_code, visibility_status)",
    # 銘柄 × 営業日の行動スナップショット。ランキングはここだけを読む。
    """
    CREATE TABLE IF NOT EXISTS short_behavior_snapshots (
        canonical_code TEXT NOT NULL,
        as_of_date TEXT NOT NULL,
        close REAL,
        adv20_shares REAL,
        adv20_value REAL,
        drawdown_52w REAL,
        price_percentile_252 REAL,
        rel_topix_20d REAL,
        rel_sector_20d REAL,
        visible_short_shares REAL,
        visible_short_ratio REAL,
        visible_institution_count INTEGER NOT NULL DEFAULT 0,
        below_threshold_count INTEGER NOT NULL DEFAULT 0,
        -- 閾値を割ったのではなく、割らないまま報告が止まったもの。
        -- どちらも合計には入れないが、意味は別なので列を分ける。
        stale_reporting_count INTEGER NOT NULL DEFAULT 0,
        largest_institution_ratio REAL,
        concentration REAL,
        ratio_change_1d REAL,
        ratio_change_5d REAL,
        ratio_change_20d REAL,
        shares_change_5d REAL,
        shares_change_20d REAL,
        pressure_adv20_5d REAL,
        pressure_adv20_20d REAL,
        visible_days_to_cover REAL,
        entry_count_20d INTEGER NOT NULL DEFAULT 0,
        reentry_count_20d INTEGER NOT NULL DEFAULT 0,
        reduction_count_20d INTEGER NOT NULL DEFAULT 0,
        threshold_exit_count_20d INTEGER NOT NULL DEFAULT 0,
        low_position_score REAL,
        short_pressure_score REAL,
        price_damage_score REAL,
        absorption_score REAL,
        covering_score REAL,
        rotation_score REAL,
        catalyst_score REAL,
        risk_score REAL,
        data_confidence REAL,
        behavior_score REAL,
        monitor_priority REAL,
        primary_state TEXT NOT NULL,
        flags_json TEXT NOT NULL DEFAULT '[]',
        components_json TEXT NOT NULL DEFAULT '{}',
        algorithm_version TEXT NOT NULL,
        generated_at TEXT NOT NULL,
        PRIMARY KEY (canonical_code, as_of_date)
    ) WITHOUT ROWID
    """,
    "CREATE INDEX IF NOT EXISTS idx_sbs_date_score ON short_behavior_snapshots(as_of_date, behavior_score DESC)",
    "CREATE INDEX IF NOT EXISTS idx_sbs_date_state ON short_behavior_snapshots(as_of_date, primary_state, behavior_score DESC)",
    # 状態が変わった日だけを残す履歴（検証の対象）。
    """
    CREATE TABLE IF NOT EXISTS short_behavior_signals (
        signal_id TEXT PRIMARY KEY,
        canonical_code TEXT NOT NULL,
        signal_date TEXT NOT NULL,
        primary_state TEXT NOT NULL,
        previous_state TEXT,
        behavior_score REAL,
        components_json TEXT NOT NULL DEFAULT '{}',
        evidence_json TEXT NOT NULL DEFAULT '{}',
        source_cutoff TEXT NOT NULL,
        algorithm_version TEXT NOT NULL,
        created_at TEXT NOT NULL
    ) WITHOUT ROWID
    """,
    "CREATE INDEX IF NOT EXISTS idx_sbsig_date ON short_behavior_signals(signal_date, primary_state)",
    "CREATE INDEX IF NOT EXISTS idx_sbsig_code ON short_behavior_signals(canonical_code, signal_date)",
)

#: 既存 `short_positions` に落としていた列を足す。住所と DIC（投資一任契約の
#: 相手方）が無いと、機関実体の正規化が名前の文字列一致だけになる。
_SHORT_POSITION_PARTIES_DDL: tuple[str, ...] = (
    "ALTER TABLE short_positions ADD COLUMN holder_address TEXT",
    "ALTER TABLE short_positions ADD COLUMN manager_name TEXT",
    "ALTER TABLE short_positions ADD COLUMN manager_address TEXT",
)

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
        regulation_level TEXT,
        regulation_severity INTEGER,
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
        -- 住所は同名別法人の切り分けに、DIC（投資一任契約の相手方）は
        -- 「報告主体」と「実際の運用者」の切り分けに使う。落とすと機関実体の
        -- 正規化が名前の文字列一致だけになる。
        holder_address TEXT,
        manager_name TEXT,
        manager_address TEXT,
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
    *_SHORT_MONITOR_DDL,
)

#: v4: 業種相対の 20 日/63 日分離 + 信用規制状態。
#:
#: 旧 `rs_sector_63d` に入っていたのは **実際には 20 日**の値だった（20 日
#: リターンと業種 20 日中位の差）。なので中身を捨てるのではなく、正しい名前の
#: ほうへ移す —— これは履歴の捏造ではなく、値に本当の名前を付け直す作業。
#: 逆に 63 日は一度も計算されたことがないので NULL のままにし、夜間バッチが
#: 翌営業日に初めて埋める（存在しなかった履歴をでっち上げない）。
_RS_SECTOR_SPLIT_DDL: tuple[str, ...] = (
    "ALTER TABLE screener_rows ADD COLUMN rs_sector_20d REAL",
    "ALTER TABLE screener_rows ADD COLUMN regulation_level TEXT",
    "ALTER TABLE screener_rows ADD COLUMN regulation_severity INTEGER",
    "UPDATE screener_rows SET rs_sector_20d = rs_sector_63d",
    "UPDATE screener_rows SET rs_sector_63d = NULL",
)

#: 前方マイグレーション連鎖: v1 → v2（強度断面）→ v3（クオート索引）
#: → v4（業種相対の周期分離・信用規制）。
#: v5: 強度断面にも信用規制を持たせる（リスク減点が規制を見るため）。
_STRENGTH_REGULATION_DDL: tuple[str, ...] = (
    "ALTER TABLE strength_rows ADD COLUMN regulation_level TEXT",
    "ALTER TABLE strength_rows ADD COLUMN regulation_severity INTEGER",
)

#: v6: 機関空売り行動モニター。既存表には触れず、導出用の表を足すだけ
#: （`short_positions` への 3 列追加を除く）。導出物はいつでも作り直せる。
_SHORT_MONITOR_MIGRATION: tuple[str, ...] = (
    *_SHORT_POSITION_PARTIES_DDL,
    *_SHORT_MONITOR_DDL,
)

#: v7: 「報告義務中のまま古くなった」件数を分けて持つ。
_STALE_REPORTING_DDL: tuple[str, ...] = (
    "ALTER TABLE short_behavior_snapshots ADD COLUMN stale_reporting_count INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE short_position_last_known ADD COLUMN stale_reporting INTEGER NOT NULL DEFAULT 0",
)

CORE_MIGRATIONS: dict[str, tuple[tuple[str, ...], str]] = {
    "jp-core-v1": (_STRENGTH_DDL, "jp-core-v2"),
    "jp-core-v2": (_QUOTE_INDEX_DDL, "jp-core-v3"),
    "jp-core-v3": (_RS_SECTOR_SPLIT_DDL, "jp-core-v4"),
    "jp-core-v4": (_STRENGTH_REGULATION_DDL, "jp-core-v5"),
    "jp-core-v5": (_SHORT_MONITOR_MIGRATION, "jp-core-v6"),
    "jp-core-v6": (_STALE_REPORTING_DDL, CORE_SCHEMA_VERSION),
}

__all__ = ["CORE_DDL", "CORE_MIGRATIONS", "CORE_SCHEMA_VERSION"]
