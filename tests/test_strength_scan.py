"""強度スキャン: 欠損感知カーネル・レジーム・夜間ビルド・ビュー・移行。"""

from __future__ import annotations

import sqlite3

import pytest

from app.repositories.core import CoreRepository
from app.repositories.core_schema import CORE_SCHEMA_VERSION
from app.services.strength_scan import (
    build_strength_rows,
    build_view_rows,
    compute_market_regime_jp,
    score_intrinsic_jp,
    sort_view_rows,
    tier_distribution,
    weighted_available,
)


def _uptrend_features(**overrides):
    features = {
        "close": 1200.0, "atr14": 24.0, "data_days": 300,
        "avg_turnover_20d": 800_000_000.0, "turnover_today": 1_500_000_000.0,
        "turnover_ratio": 1.9,
        "return_1d": 0.012, "return_5d": 0.03, "return_20d": 0.09,
        "return_63d": 0.22, "return_126d": 0.35, "return_252d": 0.6,
        "ma25": 1130.0, "ma75": 1050.0, "ma200": 950.0,
        "ma25_gap_pct": 0.06, "ma75_gap_pct": 0.14, "ma200_gap_pct": 0.26,
        "pct_from_high_252": -0.01, "prior_high_60": 1180.0,
        "drawdown_63d": -0.04, "volatility_contraction": 0.3,
    }
    features.update(overrides)
    return features


def _structure():
    return {
        "technicals": {
            "rsi14": 65.0, "rsi_score": 85.0,
            "macd": {"histogram": 4.0, "direction_pct": 0.4},
            "trend_efficiency_63d": 0.55, "ma50_slope_pct_21d": 3.2,
            "return_stability_20d": 0.015,
        },
        "price_action": {"score": 80.0, "structure": "uptrend",
                         "structure_label": "上升结构", "pattern_labels": [],
                         "spring": False, "upthrust": False},
        "vol_price": {"setup_type": "absorption_bullish", "setup_label": "多头吸收",
                      "breakout_quality_adjustment": 6.0, "false_breakout_risk": 0.0,
                      "risk_penalty_adjustment": 0.0, "tags": ["量价配合"]},
    }


def test_weighted_available_never_fills_neutral():
    result = weighted_available(
        {"a": 80.0, "b": None}, {"a": 0.5, "b": 0.5}, min_active_weight=0.25
    )
    # b 欠損 → a に全再配分。80*1.0 = 80（中立 50 で薄めない）。
    assert result["score"] == 80.0
    assert result["confidence"] == 0.5
    assert result["missing"] == ["b"]
    starved = weighted_available({"b": None}, {"b": 1.0}, min_active_weight=0.25)
    assert starved["score"] is None
    assert starved["status"] == "insufficient_data"


def test_intrinsic_uptrend_scores_high_and_reports_families():
    result = score_intrinsic_jp(_uptrend_features(), _structure(), rs_topix_63d=0.12)
    assert result["score"] is not None and result["score"] >= 70
    assert result["confidence"] > 0.9
    for family in ("short", "mid", "long", "trend", "breakout", "price_action"):
        assert result["families"][family] is not None, family
    # 量価一致 +6 が突破族へ入っている（ベース 3 成分の合成より高い）。
    assert result["breakout_quality_score"] > 0


def test_intrinsic_short_history_drops_52w_dimension():
    features = _uptrend_features(data_days=120, return_126d=None, return_252d=None)
    result = score_intrinsic_jp(features, _structure(), rs_topix_63d=0.12)
    assert result["ath_proximity"] is None  # 240本未満は52週高位を主張しない
    assert "ath_proximity" in result["family_details"]["long"]["missing"]
    assert result["score"] is not None  # 残る証拠だけで採点は続く
    assert result["confidence"] < 1.0


def test_market_regime_breadth_and_spread():
    features_by_code = {}
    market_by_code = {}
    for i in range(40):
        code = f"{1000 + i}0"
        above = i < 28  # 70% が 200 日線上
        features_by_code[code] = {
            "ma200_gap_pct": 0.1 if above else -0.1,
            "turnover_ratio": 1.4 if i % 2 == 0 else 0.7,
            "return_20d": 0.06 if i < 20 else -0.01,
        }
        market_by_code[code] = "0111" if i < 30 else "0113"
    # グロース側を 30 銘柄に満たない状態にする → spread は欠損のまま。
    topix = [{"close": 2500.0 + i} for i in range(210)]
    regime = compute_market_regime_jp(topix, features_by_code, market_by_code)
    assert regime["dims"]["breadth"] == 70.0
    assert regime["dims"]["volume"] == 50.0
    assert regime["dims"]["risk_on_spread"] is None
    assert regime["score"] is not None
    assert regime["label"] in ("順風", "中立", "逆風")


def test_build_and_view_rows(tmp_path):
    securities = {
        "72030": {"canonical_code": "72030", "name_ja": "トヨタ自動車",
                   "sector33_name": "輸送用機器", "sector33_code": "3700",
                   "market_code": "0111", "market_name": "プライム"},
        "67580": {"canonical_code": "67580", "name_ja": "ソニーグループ",
                   "sector33_name": "電気機器", "sector33_code": "3650",
                   "market_code": "0111", "market_name": "プライム"},
    }
    features = {
        "72030": _uptrend_features(),
        "67580": _uptrend_features(return_63d=0.05, return_20d=0.02, turnover_ratio=0.9),
    }
    structures = {"72030": _structure(), "67580": _structure()}
    rows = build_strength_rows(
        trade_date="2026-07-31",
        features_by_code=features,
        structure_by_code=structures,
        securities=securities,
        topix_return_63d=0.04,
    )
    assert len(rows) == 2
    by_code = {row["canonical_code"]: row for row in rows}
    assert by_code["72030"]["intrinsic_score"] > by_code["67580"]["intrinsic_score"]
    assert by_code["72030"]["global_rank_percentile"] == 100.0
    assert by_code["67580"]["global_rank_percentile"] == 0.0

    regime = {"score": 70.0, "confidence": 1.0, "label": "順風", "dims": {}, "warnings": []}
    view = build_view_rows(rows, regime, profile="balanced")
    top = max(view, key=lambda r: r["ranking_score"])
    assert top["canonical_code"] == "72030"
    assert top["classification"] in ("质量趋势", "放量突破", "相对强势", "观察")
    assert top["tags"]
    # profile を変えると profile_fit が変わる（intrinsic は不変）。
    aggressive = build_view_rows(rows, regime, profile="aggressive")
    assert aggressive[0]["intrinsic_score"] == view[0]["intrinsic_score"]
    sort_view_rows(view, "short")
    distribution = tier_distribution(view, "all")
    assert distribution["total"] == 2

    # 永続化の往復。
    repo = CoreRepository(tmp_path / "core.db")
    repo.initialize()
    written = repo.replace_strength_rows(rows, trade_date="2026-07-31", regime=regime)
    assert written == 2
    stored = repo.strength_rows_all()
    assert len(stored) == 2
    assert stored[0]["details"]["families"]
    meta = repo.strength_meta()
    assert meta["trade_date"] == "2026-07-31"
    assert meta["regime"]["label"] == "順風"


def test_core_v1_database_migrates_forward(tmp_path):
    db_path = tmp_path / "core.db"
    repo = CoreRepository(db_path)
    repo.initialize()
    # v1 の実ファイルを再現: 強度テーブルを落とし、版数を巻き戻す。
    with sqlite3.connect(db_path) as connection:
        connection.execute("DROP TABLE strength_rows")
        connection.execute("DROP TABLE strength_meta")
        connection.execute(
            "UPDATE jp_core_schema SET version='jp-core-v1', checksum='deadbeef' WHERE id=1"
        )
        connection.commit()
    migrated = CoreRepository(db_path)
    migrated.initialize()  # v1 → v2 → v3 → v4 の連鎖前方移行
    assert migrated.strength_meta() is None  # 表はあるが断面は未生成
    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            "SELECT version FROM jp_core_schema WHERE id=1"
        ).fetchone()
        indexes = {r[0] for r in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='daily_bars'"
        )}
    # 版数はコード側の定数に追随させる（スキーマを上げるたびに落ちないように）
    assert row[0] == CORE_SCHEMA_VERSION
    assert "idx_daily_bars_date_quote" in indexes
    # v4 で足した列が実在すること（ALTER が本当に流れたか）
    with sqlite3.connect(db_path) as connection:
        columns = {r[1] for r in connection.execute("PRAGMA table_info(screener_rows)")}
    assert {"rs_sector_20d", "regulation_level", "regulation_severity"} <= columns
    # 未知の版数は従来通り拒否。
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "UPDATE jp_core_schema SET version='jp-core-v0' WHERE id=1"
        )
        connection.commit()
    stranger = CoreRepository(db_path)
    with pytest.raises(Exception):
        stranger.initialize()
