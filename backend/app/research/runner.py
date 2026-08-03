"""研究バッチ本体: 点時の断面を刻み → 結果を測り → 走步検証にかける。

Web プロセスからは呼ばない（doc §十一）。重い履歴計算はワーカーか独立
コマンドで回し、ページ表示は保存済みの結果だけを読む。

大規模計算の作法をここで守る:
  * 評価日ごとのバッチ処理（全期間をメモリに載せない）
  * 中断・再開可能（日付単位のチェックポイント）
  * 結果はバージョン付き（スコア版が変われば別の行として残る）
  * 同じ版で再実行しても冪等
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from app.repositories.core import CoreRepository
from app.services.radar.scoring import SCORE_VERSION
from app.services.strength_scan import STRENGTH_SCORE_VERSION

from .outcomes import HORIZONS, compute_outcome
from .replay import POINT_IN_TIME_LIMITS, REPLAY_VERSION, replay_cross_section, sample_dates
from .walk_forward import evaluate_window, summarise_run, walk_forward_windows

RESEARCH_SCHEMA_VERSION = "jp-research-v1"

_DDL = (
    """
    CREATE TABLE IF NOT EXISTS signal_snapshots (
        run_id TEXT NOT NULL,
        canonical_code TEXT NOT NULL,
        signal_date TEXT NOT NULL,
        engine_version TEXT NOT NULL,
        score_version TEXT NOT NULL,
        replay_version TEXT NOT NULL,
        market_code TEXT,
        sector33_code TEXT,
        score REAL,
        intrinsic_score REAL,
        confidence REAL,
        close REAL,
        atr14 REAL,
        pivot_price REAL,
        invalidation_price REAL,
        data_days INTEGER,
        liquidity_known INTEGER,
        missing_json TEXT NOT NULL DEFAULT '[]',
        features_json TEXT NOT NULL DEFAULT '{}',
        source_data_cutoff TEXT NOT NULL,
        generated_at TEXT NOT NULL,
        PRIMARY KEY (run_id, canonical_code, signal_date)
    ) WITHOUT ROWID
    """,
    "CREATE INDEX IF NOT EXISTS idx_snap_date ON signal_snapshots(signal_date)",
    """
    CREATE TABLE IF NOT EXISTS signal_outcomes (
        run_id TEXT NOT NULL,
        canonical_code TEXT NOT NULL,
        signal_date TEXT NOT NULL,
        outcome_json TEXT NOT NULL,
        computed_at TEXT NOT NULL,
        PRIMARY KEY (run_id, canonical_code, signal_date)
    ) WITHOUT ROWID
    """,
    """
    CREATE TABLE IF NOT EXISTS research_runs (
        run_id TEXT PRIMARY KEY,
        started_at TEXT NOT NULL,
        finished_at TEXT,
        params_json TEXT NOT NULL DEFAULT '{}',
        checkpoint_date TEXT,
        report_json TEXT
    ) WITHOUT ROWID
    """,
)


def _utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class RunParams:
    start_date: str
    end_date: str
    every_n_trading_days: int = 5
    min_data_days: int = 120
    min_avg_turnover_jpy: float = 100_000_000.0
    train_days: int = 120
    test_days: int = 60
    horizon: int = 20
    score_field: str = "score"

    def as_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)

    def run_id(self) -> str:
        """同じ条件・同じスコア版なら同じ ID（再実行が上書きになる = 冪等）。

        スコア版が変われば別 ID になるので、**過去の結果を壊さない**
        （doc §十二「修改评分版本不会覆盖旧结果」）。
        """

        import hashlib

        payload = json.dumps(
            {**self.as_dict(), "score": SCORE_VERSION, "strength": STRENGTH_SCORE_VERSION,
             "replay": REPLAY_VERSION},
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


class ResearchStore:
    """研究結果だけの別 DB。本番の読み書きと競合させない。"""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    def _connect(self) -> sqlite3.Connection:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self._path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def initialize(self) -> None:
        with self._connect() as connection:
            for statement in _DDL:
                connection.execute(statement)

    def start_run(self, run_id: str, params: RunParams) -> str | None:
        """既存の run があればチェックポイント日付を返す（再開用）。"""

        with self._connect() as connection:
            row = connection.execute(
                "SELECT checkpoint_date FROM research_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            if row is not None:
                return row["checkpoint_date"]
            connection.execute(
                "INSERT INTO research_runs (run_id, started_at, params_json) VALUES (?, ?, ?)",
                (run_id, _utc_now(), json.dumps(params.as_dict(), sort_keys=True)),
            )
        return None

    def write_snapshots(self, rows: Sequence[Mapping[str, Any]]) -> int:
        if not rows:
            return 0
        columns = (
            "run_id", "canonical_code", "signal_date", "engine_version", "score_version",
            "replay_version", "market_code", "sector33_code", "score", "intrinsic_score",
            "confidence", "close", "atr14", "pivot_price", "invalidation_price",
            "data_days", "liquidity_known", "missing_json", "features_json",
            "source_data_cutoff", "generated_at",
        )
        placeholders = ", ".join("?" for _ in columns)
        sql = (
            f"INSERT INTO signal_snapshots ({', '.join(columns)}) VALUES ({placeholders}) "
            f"ON CONFLICT (run_id, canonical_code, signal_date) DO UPDATE SET "
            + ", ".join(f"{column} = excluded.{column}" for column in columns[3:])
        )
        with self._connect() as connection:
            connection.executemany(sql, [tuple(row.get(c) for c in columns) for row in rows])
        return len(rows)

    def write_outcomes(self, run_id: str, outcomes: Sequence[Mapping[str, Any]]) -> int:
        if not outcomes:
            return 0
        now = _utc_now()
        with self._connect() as connection:
            connection.executemany(
                "INSERT INTO signal_outcomes (run_id, canonical_code, signal_date, "
                "outcome_json, computed_at) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT (run_id, canonical_code, signal_date) DO UPDATE SET "
                "outcome_json = excluded.outcome_json, computed_at = excluded.computed_at",
                [
                    (run_id, row["canonical_code"], row["signal_date"], json.dumps(row), now)
                    for row in outcomes
                ],
            )
        return len(outcomes)

    def checkpoint(self, run_id: str, date: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE research_runs SET checkpoint_date = ? WHERE run_id = ?", (date, run_id)
            )

    def finish(self, run_id: str, report: Mapping[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE research_runs SET finished_at = ?, report_json = ? WHERE run_id = ?",
                (_utc_now(), json.dumps(report, ensure_ascii=False), run_id),
            )

    def joined_records(self, run_id: str) -> list[dict[str, Any]]:
        """スナップショット × 結果（走步検証の入力）。"""

        with self._connect() as connection:
            rows = connection.execute(
                "SELECT s.canonical_code, s.signal_date, s.score, s.intrinsic_score, "
                "       s.market_code, s.sector33_code, o.outcome_json "
                "FROM signal_snapshots s JOIN signal_outcomes o "
                "  ON o.run_id = s.run_id AND o.canonical_code = s.canonical_code "
                " AND o.signal_date = s.signal_date "
                "WHERE s.run_id = ?",
                (run_id,),
            ).fetchall()
        records = []
        for row in rows:
            record = dict(row)
            record.update(json.loads(record.pop("outcome_json")))
            records.append(record)
        return records

    def report(self, run_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT report_json FROM research_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
        return json.loads(row["report_json"]) if row and row["report_json"] else None


def run_backtest(
    repository: CoreRepository,
    store: ResearchStore,
    params: RunParams,
    *,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """点時断面 → 結果 → 走步検証 の一括実行（再開可能）。"""

    store.initialize()
    run_id = params.run_id()
    resume_from = store.start_run(run_id, params)

    calendar = repository.trading_days_between(params.start_date, params.end_date)
    evaluation_dates = sample_dates(
        calendar, every=params.every_n_trading_days, skip_last=max(HORIZONS)
    )
    if resume_from:
        evaluation_dates = [date for date in evaluation_dates if date > resume_from]

    securities = {
        row["canonical_code"]: row
        for row in repository.list_securities(active_only=False)
        if row.get("sector33_code") and row.get("sector33_code") != "9999"
    }
    sectors_by_code = {code: row.get("sector33_code") for code, row in securities.items()}

    # 320 営業日分の履歴が要る（252 日高値 + 移動平均）。評価日ごとに再読込
    # すると I/O が爆発するので、全期間を 1 度だけ読んで日付で切る。
    lookback_start = repository.trading_days_between("1900-01-01", params.start_date)
    history_start = lookback_start[-400] if len(lookback_start) >= 400 else params.start_date
    bars_by_code = repository.bars_matrix_since(history_start)
    topix_bars = repository.index_series("0000", start_date=history_start)

    if progress:
        progress(
            f"run={run_id} 評価日={len(evaluation_dates)} 銘柄={len(bars_by_code)} "
            f"履歴開始={history_start}"
        )

    total_snapshots = 0
    for index, as_of in enumerate(evaluation_dates, start=1):
        rows = replay_cross_section(
            {code: bars for code, bars in bars_by_code.items() if code in securities},
            as_of,
            topix_bars=topix_bars,
            sectors_by_code=sectors_by_code,
            min_data_days=params.min_data_days,
        )
        snapshots: list[dict[str, Any]] = []
        outcomes: list[dict[str, Any]] = []
        for row in rows:
            turnover = row.features.get("avg_turnover_20d")
            if turnover is None or turnover < params.min_avg_turnover_jpy:
                continue    # 欠損は「合格」ではない（本番の判定と揃える）
            base = row.structure.get("base") or {}
            priority = ((row.scores or {}).get("alert_priority") or {}).get("score")
            security = securities.get(row.canonical_code) or {}
            snapshots.append(
                {
                    "run_id": run_id,
                    "canonical_code": row.canonical_code,
                    "signal_date": as_of,
                    "engine_version": REPLAY_VERSION,
                    "score_version": SCORE_VERSION,
                    "replay_version": REPLAY_VERSION,
                    "market_code": security.get("market_code"),
                    "sector33_code": security.get("sector33_code"),
                    "score": priority if params.score_field == "score" else row.intrinsic.get("score"),
                    "intrinsic_score": row.intrinsic.get("score"),
                    "confidence": row.intrinsic.get("confidence"),
                    "close": row.features.get("close"),
                    "atr14": row.features.get("atr14"),
                    "pivot_price": base.get("pivot_price"),
                    "invalidation_price": base.get("invalidation_price"),
                    "data_days": row.features.get("data_days"),
                    "liquidity_known": 1 if row.features.get("liquidity_known") else 0,
                    "missing_json": json.dumps(
                        ((row.scores or {}).get("alert_priority") or {}).get("missing") or []
                    ),
                    "features_json": json.dumps(row.as_dict(), ensure_ascii=False),
                    "source_data_cutoff": as_of,
                    "generated_at": _utc_now(),
                }
            )
            outcome = compute_outcome(
                canonical_code=row.canonical_code,
                signal_date=as_of,
                bars=bars_by_code.get(row.canonical_code) or [],
                signal_close=row.features.get("close"),
                atr14=row.features.get("atr14"),
                stop_price=base.get("invalidation_price"),
                topix_bars=topix_bars,
            )
            outcomes.append(outcome.as_dict())

        store.write_snapshots(snapshots)
        store.write_outcomes(run_id, outcomes)
        store.checkpoint(run_id, as_of)
        total_snapshots += len(snapshots)
        if progress and index % 10 == 0:
            progress(f"  {index}/{len(evaluation_dates)} {as_of} 累計={total_snapshots}")

    return evaluate_run(store, params, calendar=calendar, run_id=run_id)


def evaluate_run(
    store: "ResearchStore",
    params: RunParams,
    *,
    calendar: Sequence[str] | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """保存済みスナップショットだけで走步検証をやり直す。

    断面の再計算（数時間）を伴わずに評価軸だけ変えられる。スナップショットを
    残している意味はここにある —— 判定の切り方を変えるたびに履歴を作り直す
    必要はないし、作り直せば「同じ過去」が版ごとに変わってしまう。
    """

    run_id = run_id or params.run_id()
    records = store.joined_records(run_id)
    days = list(calendar or sorted({str(r.get("signal_date")) for r in records}))
    windows = walk_forward_windows(
        days, train_days=params.train_days, test_days=params.test_days
    )
    results = [
        evaluate_window(records, window, horizon=params.horizon) for window in windows
    ]
    report = {
        "run_id": run_id,
        "params": params.as_dict(),
        "score_version": SCORE_VERSION,
        "strength_version": STRENGTH_SCORE_VERSION,
        "replay_version": REPLAY_VERSION,
        "trading_days": len(days),
        "evaluation_dates": len({str(r.get("signal_date")) for r in records}),
        "signals": len(records),
        "windows": [result.as_dict() for result in results],
        "summary": summarise_run(results),
        "point_in_time_limits": list(POINT_IN_TIME_LIMITS),
    }
    store.finish(run_id, report)
    return report


__all__ = [
    "RESEARCH_SCHEMA_VERSION",
    "ResearchStore",
    "RunParams",
    "run_backtest",
]
