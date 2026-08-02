"""日本の経済指標カレンダー（手動整備・官公庁の公表スケジュール由来）。

規律:
- 日付は官公庁の公表予定から採録し、``confirmed=True`` は一次資料で日付を
  確認済みのもの。``confirmed=False`` は官庁の公表ルール（例: 全国CPIは
  19日を含む週の金曜 8:30）から導出した **目安** で、UI は「目安」バッジを
  必ず表示する。
- 実績値（actual）は未接続。予定だけを扱い、値をでっち上げない。
- 出典 URL を各行に持つ。スケジュール改定があれば手動でこのファイルを更新。

採録日: 2026-08-02。対象: 2026-08 〜 2026-12。
"""

from __future__ import annotations

from typing import Any

ECON_CALENDAR_VERSION = "jp-econ-calendar-2026h2-v1"

_BOJ_CAL = "https://www.boj.or.jp/about/calendar/index.htm"
_BOJ_MPM = "https://www.boj.or.jp/mopo/mpmsche_minu/index.htm"
_ESRI_QE = "https://www.esri.cao.go.jp/jp/sna/kouhyou/kouhyou_top.html"
_STAT_CPI = "https://www.stat.go.jp/data/cpi/index.html"
_BOJ_TK = "https://www.boj.or.jp/statistics/tk/index.htm"

# category: 金融政策 | 物価 | 景気 | 統計(金融)
# importance: high | medium | low
ECON_EVENTS: tuple[dict[str, Any], ...] = (
    {"date": "2026-08-04", "time_jst": "08:50", "name_ja": "マネタリーベース（7月）", "category": "統計(金融)", "importance": "low", "organizer": "日本銀行", "confirmed": True, "source_url": _BOJ_CAL},
    {"date": "2026-08-05", "time_jst": "08:50", "name_ja": "金融政策決定会合 議事要旨（6月15-16日開催分）", "category": "金融政策", "importance": "medium", "organizer": "日本銀行", "confirmed": True, "source_url": _BOJ_CAL},
    {"date": "2026-08-10", "time_jst": "08:50", "name_ja": "金融政策決定会合 主な意見（7月30-31日開催分）", "category": "金融政策", "importance": "medium", "organizer": "日本銀行", "confirmed": True, "source_url": _BOJ_CAL},
    {"date": "2026-08-12", "time_jst": "08:50", "name_ja": "マネーストック（7月）", "category": "統計(金融)", "importance": "low", "organizer": "日本銀行", "confirmed": True, "source_url": _BOJ_CAL},
    {"date": "2026-08-13", "time_jst": "08:50", "name_ja": "企業物価指数（7月）", "category": "物価", "importance": "medium", "organizer": "日本銀行", "confirmed": True, "source_url": _BOJ_CAL},
    {"date": "2026-08-17", "time_jst": "08:50", "name_ja": "四半期別GDP速報 2026年4-6月期（1次速報）", "category": "景気", "importance": "high", "organizer": "内閣府", "confirmed": False, "source_url": _ESRI_QE, "note": "1次速報は四半期終了後約6週間後の月曜が通例。確定日は内閣府の公表予定で要確認"},
    {"date": "2026-08-21", "time_jst": "08:30", "name_ja": "全国消費者物価指数 CPI（7月分）", "category": "物価", "importance": "high", "organizer": "総務省統計局", "confirmed": True, "source_url": _STAT_CPI},
    {"date": "2026-08-26", "time_jst": "08:50", "name_ja": "企業向けサービス価格指数（7月）", "category": "物価", "importance": "medium", "organizer": "日本銀行", "confirmed": True, "source_url": _BOJ_CAL},
    {"date": "2026-08-28", "time_jst": "08:30", "name_ja": "東京都区部消費者物価指数（8月中旬速報値）", "category": "物価", "importance": "medium", "organizer": "総務省統計局", "confirmed": True, "source_url": _STAT_CPI},
    {"date": "2026-09-08", "time_jst": "08:50", "name_ja": "四半期別GDP速報 2026年4-6月期（2次速報）", "category": "景気", "importance": "high", "organizer": "内閣府", "confirmed": True, "source_url": _ESRI_QE},
    {"date": "2026-09-17", "time_jst": "", "name_ja": "日銀金融政策決定会合（1日目）", "category": "金融政策", "importance": "high", "organizer": "日本銀行", "confirmed": True, "source_url": _BOJ_MPM},
    {"date": "2026-09-18", "time_jst": "12:00", "name_ja": "日銀金融政策決定会合 結果発表・総裁会見（15:30）", "category": "金融政策", "importance": "high", "organizer": "日本銀行", "confirmed": True, "source_url": _BOJ_MPM, "note": "声明は昼頃、総裁会見は15:30"},
    {"date": "2026-09-18", "time_jst": "08:30", "name_ja": "全国消費者物価指数 CPI（8月分）", "category": "物価", "importance": "high", "organizer": "総務省統計局", "confirmed": False, "source_url": _STAT_CPI, "note": "全国CPIは19日を含む週の金曜8:30が公表ルール（導出値）"},
    {"date": "2026-10-01", "time_jst": "08:50", "name_ja": "日銀短観（9月調査）", "category": "景気", "importance": "high", "organizer": "日本銀行", "confirmed": False, "source_url": _BOJ_TK, "note": "4・7・10月調査は月初公表が通例（導出値）"},
    {"date": "2026-10-23", "time_jst": "08:30", "name_ja": "全国消費者物価指数 CPI（9月分）", "category": "物価", "importance": "high", "organizer": "総務省統計局", "confirmed": False, "source_url": _STAT_CPI, "note": "公表ルールからの導出値"},
    {"date": "2026-10-29", "time_jst": "", "name_ja": "日銀金融政策決定会合（1日目）", "category": "金融政策", "importance": "high", "organizer": "日本銀行", "confirmed": True, "source_url": _BOJ_MPM},
    {"date": "2026-10-30", "time_jst": "12:00", "name_ja": "日銀金融政策決定会合 結果発表・展望レポート・総裁会見", "category": "金融政策", "importance": "high", "organizer": "日本銀行", "confirmed": True, "source_url": _BOJ_MPM, "note": "経済・物価情勢の展望（展望レポート）公表回"},
    {"date": "2026-11-16", "time_jst": "08:50", "name_ja": "四半期別GDP速報 2026年7-9月期（1次速報）", "category": "景気", "importance": "high", "organizer": "内閣府", "confirmed": True, "source_url": _ESRI_QE},
    {"date": "2026-11-20", "time_jst": "08:30", "name_ja": "全国消費者物価指数 CPI（10月分）", "category": "物価", "importance": "high", "organizer": "総務省統計局", "confirmed": False, "source_url": _STAT_CPI, "note": "公表ルールからの導出値"},
    {"date": "2026-12-08", "time_jst": "08:50", "name_ja": "四半期別GDP速報 2026年7-9月期（2次速報）", "category": "景気", "importance": "medium", "organizer": "内閣府", "confirmed": True, "source_url": _ESRI_QE},
    {"date": "2026-12-14", "time_jst": "08:50", "name_ja": "日銀短観（12月調査）", "category": "景気", "importance": "high", "organizer": "日本銀行", "confirmed": False, "source_url": _BOJ_TK, "note": "12月調査は12月中旬公表が通例（導出値）"},
    {"date": "2026-12-17", "time_jst": "", "name_ja": "日銀金融政策決定会合（1日目）", "category": "金融政策", "importance": "high", "organizer": "日本銀行", "confirmed": True, "source_url": _BOJ_MPM},
    {"date": "2026-12-18", "time_jst": "12:00", "name_ja": "日銀金融政策決定会合 結果発表・総裁会見", "category": "金融政策", "importance": "high", "organizer": "日本銀行", "confirmed": True, "source_url": _BOJ_MPM},
    {"date": "2026-12-18", "time_jst": "08:30", "name_ja": "全国消費者物価指数 CPI（11月分）", "category": "物価", "importance": "high", "organizer": "総務省統計局", "confirmed": False, "source_url": _STAT_CPI, "note": "公表ルールからの導出値"},
)

COVERAGE_NOTE_JA = (
    "官公庁の公表スケジュールから手動整備（採録 2026-08-02）。「目安」印は公表ルールからの"
    "導出値で、確定日は各官庁の発表に従う。実績値・市場予想は未接続。"
)


def econ_events_between(start_date: str, end_date: str) -> list[dict[str, Any]]:
    rows = [
        dict(event)
        for event in ECON_EVENTS
        if start_date <= event["date"] <= end_date
    ]
    rows.sort(key=lambda event: (event["date"], event.get("time_jst") or "99:99"))
    return rows


__all__ = ["COVERAGE_NOTE_JA", "ECON_CALENDAR_VERSION", "ECON_EVENTS", "econ_events_between"]
