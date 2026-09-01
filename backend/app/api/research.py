"""研究結果の読み出し（読み取り専用）。

**ここでは何も計算しない。** 走步検証は `python -m app.research` でワーカー側
または独立コマンドとして回し、この API は保存済みのレポートを返すだけ
（doc §十一「回测和评分校准应在 Worker 或独立研究命令中执行，不阻塞网页服务」）。

ページ表示のたびに数時間の履歴計算が走る、という事故を構造的に防ぐため、
リポジトリは読み取り専用で開き、run を新規作成する経路をここには置かない。
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.data_paths import get_data_paths

router = APIRouter(prefix="/api/research", tags=["research"])

RESEARCH_API_VERSION = "jp-research-api-v1"


def _db_path() -> Path:
    return get_data_paths().root / "jp-research.db"


def _connect() -> sqlite3.Connection:
    path = _db_path()
    if not path.is_file():
        raise HTTPException(status_code=503, detail={"code": "research_not_run"})
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    return connection


@router.get("/runs")
def list_runs(limit: int = Query(default=20, ge=1, le=100)) -> dict[str, Any]:
    """実行済みの検証一覧（新しい順）。未完了のものも隠さず出す。"""

    connection = _connect()
    try:
        rows = connection.execute(
            "SELECT run_id, started_at, finished_at, params_json, checkpoint_date, "
            "       (report_json IS NOT NULL) AS has_report "
            "FROM research_runs ORDER BY started_at DESC LIMIT ?",
            (int(limit),),
        ).fetchall()
    except sqlite3.Error:
        raise HTTPException(status_code=503, detail={"code": "research_not_initialized"})
    finally:
        connection.close()

    runs = []
    for row in rows:
        item = dict(row)
        item["params"] = json.loads(item.pop("params_json") or "{}")
        item["has_report"] = bool(item["has_report"])
        item["complete"] = bool(item.get("finished_at"))
        runs.append(item)
    return {"version": RESEARCH_API_VERSION, "runs": runs}


@router.get("/report")
def get_report(run_id: str | None = Query(default=None)) -> dict[str, Any]:
    """1 回分のレポート。`run_id` 省略時は最新の完了済み。"""

    connection = _connect()
    try:
        if run_id:
            row = connection.execute(
                "SELECT run_id, report_json, finished_at FROM research_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        else:
            row = connection.execute(
                "SELECT run_id, report_json, finished_at FROM research_runs "
                "WHERE report_json IS NOT NULL ORDER BY finished_at DESC LIMIT 1"
            ).fetchone()
    except sqlite3.Error:
        raise HTTPException(status_code=503, detail={"code": "research_not_initialized"})
    finally:
        connection.close()

    if row is None:
        # 完了済みが 1 つも無い。ここで「一度も走っていない」と言い切ると、
        # 走行中の run があるときに嘘になる（実際に本番で 404 を返していた）。
        # 未完了の run があるなら「走行中」と区別して返す。
        connection = _connect()
        try:
            pending = connection.execute(
                "SELECT 1 FROM research_runs WHERE report_json IS NULL LIMIT 1"
            ).fetchone()
        except sqlite3.Error:
            pending = None
        finally:
            connection.close()
        if pending is not None:
            raise HTTPException(status_code=409, detail={"code": "run_in_progress"})
        raise HTTPException(status_code=404, detail={"code": "run_not_found"})
    if not row["report_json"]:
        # 走行中。checkpoint まで進んでいることは分かるので、その旨を返す。
        raise HTTPException(status_code=409, detail={"code": "run_in_progress"})
    report = json.loads(row["report_json"])
    return {"version": RESEARCH_API_VERSION, "finished_at": row["finished_at"], **report}


__all__ = ["RESEARCH_API_VERSION", "router"]
