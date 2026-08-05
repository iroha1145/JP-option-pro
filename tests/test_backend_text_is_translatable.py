"""バックエンドが返す表示文は、フロントの辞書に必ず載っていること。

表示文の一部はサーバ側で組み立てる（相手の言語は知らない —— 応答は ETag で
共有される）。そのため **原文を msgid にして** 返し、置換だけフロントの
`t()` が行う。辞書に載っていない文は ja/en でも原文のまま画面に出る。

ここが素通しだと同じことが何度でも起きる。実際に 2 回起きた:

1. 空売りモニターの `現在の分類` 周辺がまるごと中文で出ていた
2. 網羅監査（2026-08-04）で、強度スキャンの警告・評価根拠、ニュースの
   イベント分類、決算の覆盖口径など **60 件以上** が同じ状態だった

なので機械的に確かめる。集める先は 3 通り:

- `display_text.line()` / `enumeration()` に渡すリテラル（**AST で走査**）。
  「表示文はこの関数を通す」という約束さえ守れば、新しい文も自動で網に入る。
- 表示ラベルの定数（`_STRUCTURE_LABELS` などを **import して** 読む。
  テスト側に文字列を書き写さない —— 写した瞬間から腐る）
- 分岐でしか出ない文は、関数を実際に呼んで集める（`describe` / `classify`）

なお **中文の msgid に日本語が混ざっている問題は、この門では見ない。**
それは「中文画面に日本語が漏れる」別件で、ここが見るのは ja/en が出るか。
"""

import ast
import json
import re
from pathlib import Path

import pytest

from app.domain import econ_calendar
from app.research.replay import POINT_IN_TIME_LIMITS
from app.services import strength_scan
from app.services.earnings_service import UPCOMING_COVERAGE_NOTE
from app.services.news.classify import CATEGORY_WEIGHTS
from app.services.radar.price_action import _PATTERN_LABELS, _STRUCTURE_LABELS
from app.services.short_monitor import explain
from app.services.short_monitor.scoring import VALIDATION
from app.services.short_monitor.states import ORDERED_STATES

ROOT = Path(__file__).resolve().parents[1]
DICT_PATH = ROOT / "frontend-src/src/i18n/dict/index.ts"
BACKEND = ROOT / "backend/app"

#: `display_text` の入口。ここに渡る第 1 引数がそのまま msgid になる。
TEXT_BUILDERS = {"line", "enumeration"}


#: 文字列リテラル。**シングルもダブルもある**（`["Owner's list", …]`）。
_STRING = re.compile(r"'((?:[^'\\]|\\.)*)'|\"((?:[^\"\\]|\\.)*)\"")


def _unescape(text: str) -> str:
    """JS のエスケープを解く（`\\'` も `\\u2019` も来る）。"""

    inner = re.sub(r'(?<!\\)"', r'\\"', text.replace("\\'", "'"))
    try:
        return json.loads(f'"{inner}"')
    except json.JSONDecodeError:  # pragma: no cover — 想定外の書き方は素通し
        return text


#: 1 エントリの頭。キーは **クオート付き / 無し** が混在する。
#: キー部分は改行を跨がせない（`[^\S\n]` / `[^…\n]`）—— `\s` も `[^:]` も改行に
#: 当たるので、ファイル全体に掛けると直前のコメント行が次のキー行を丸ごと
#: 飲み込み、本物のキーが集合から落ちる。気づかないと誤検出になる。
#: 値の `[` は次の行に折り返すことがあるので、そこだけ `\s*` を許す。
_ENTRY_HEAD = re.compile(
    r"(?m)^[^\S\n]*(?:'((?:[^'\\]|\\.)*)'|([^\s'\"\[\]{}:,/*][^:'\"\n]*?))[^\S\n]*:\s*\["
)


def _dictionary_entries() -> dict[str, tuple[str, str]]:
    """辞書を `{msgid: (英, 日)}` に読む。

    キーの有無だけでなく **中身が空でないか** も見たいので、値まで取る
    ——「辞書にはあるが訳文が空」は、フォールバックで原文に戻るだけで
    未収録と同じ結果になる。
    """

    source = DICT_PATH.read_text(encoding="utf-8")
    entries: dict[str, tuple[str, str]] = {}
    for match in _ENTRY_HEAD.finditer(source):
        quoted, bare = match.group(1), match.group(2)
        key = _unescape(quoted) if quoted is not None else bare.strip()
        # 対応する `]` まで読む。文字列の中の括弧は数えない。
        depth, index = 1, match.end()
        while index < len(source) and depth:
            char = source[index]
            if char in "'\"":
                index += 1
                while index < len(source) and source[index] != char:
                    index += 2 if source[index] == "\\" else 1
            elif char == "[":
                depth += 1
            elif char == "]":
                depth -= 1
            index += 1
        values = [
            _unescape(m.group(1) if m.group(1) is not None else m.group(2))
            for m in _STRING.finditer(source[match.end() : index - 1])
        ]
        if len(values) >= 2:
            entries[key] = (values[0], values[1])
    return entries


def _dictionary_keys() -> set[str]:
    return set(_dictionary_entries())


def _text_builder_literals() -> dict[str, str]:
    """`line("…")` / `enumeration("…", …)` に渡るリテラル → どのファイルか。

    `line(x)` のように変数を渡している箇所は拾えない。拾えたものだけを見る
    ——「表示文は必ず `line()` を通す」の側を約束として守る。
    """

    found: dict[str, str] = {}
    for path in sorted(BACKEND.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover — 構文エラーは別のテストの仕事
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if name.lstrip("_") not in TEXT_BUILDERS:
                continue
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                found.setdefault(first.value, str(path.relative_to(ROOT)))
            elif isinstance(first, ast.Dict):
                # `line({...}.get(level, "既定"))` の形。分岐の全部を拾う。
                for value in [*first.values, *(a for a in ast.walk(first))]:
                    if isinstance(value, ast.Constant) and isinstance(value.value, str):
                        found.setdefault(value.value, str(path.relative_to(ROOT)))
    return found


def _label_constants() -> dict[str, str]:
    """表示ラベルの定数。**import して読む** —— 書き写すと必ず腐る。"""

    groups: dict[str, list[str]] = {
        "radar/price_action._STRUCTURE_LABELS": list(_STRUCTURE_LABELS.values()),
        "radar/price_action._PATTERN_LABELS": list(_PATTERN_LABELS.values()),
        "strength_scan.REGIME_LABELS": [*strength_scan.REGIME_LABELS,
                                        strength_scan.REGIME_SPREAD_LABEL],
        # ニュースの分類は **API の絞り込み値そのもの**（画面にも出る）。
        "news/classify.CATEGORY_WEIGHTS": list(CATEGORY_WEIGHTS),
        "domain/econ_calendar": sorted(
            {str(event["category"]) for event in econ_calendar.ECON_EVENTS}
        ),
        "research/replay.POINT_IN_TIME_LIMITS": list(POINT_IN_TIME_LIMITS),
        "earnings_service.UPCOMING_COVERAGE_NOTE": [UPCOMING_COVERAGE_NOTE],
        "short_monitor/explain.STATE_LABELS": list(explain.STATE_LABELS.values()),
        "short_monitor/scoring.VALIDATION": [VALIDATION["summary"]],
    }
    return {text: origin for origin, texts in groups.items() for text in texts}


def _classification_labels() -> dict[str, str]:
    """`strength_scan.classify()` の戻り値。分岐でしか出ないので実際に呼ぶ。"""

    rows = [
        {"ma_alignment_pct": 80.0},
        {"turnover_ratio": 2.0, "ath_proximity": 95.0},
        {"rs_topix_63d": 1.0},
        {"details": {"technicals": {"rsi14": 40.0}}},
        {},
    ]
    found: dict[str, str] = {}
    for row in rows:
        for score in (None, 90.0, 74.0, 66.0, 60.0, 20.0):
            for penalty in (0.0, 20.0):
                found.setdefault(strength_scan.classify(row, score, penalty),
                                 "strength_scan.classify()")
    return found


def _every_template() -> set[str]:
    """describe() の全分岐を通して、出しうるテンプレートを集める。"""

    holders_full = (
        [{"visibility_status": "reporting", "stale_reporting": False}] * 2
        + [{"visibility_status": "reporting", "stale_reporting": True,
            "state_age_trading_days": 900}]
        + [{"visibility_status": "below_public_threshold"}]
        + [{"visibility_status": "unknown"}]
    )
    snapshots = [
        # 全部載せ（在册合計あり）
        {
            "visible_short_ratio": 0.0523, "reported_in_scope_ratio": 0.0912,
            "pressure_adv20_20d": 0.07, "rel_topix_20d": 0.19, "rel_sector_20d": 0.15,
            "visible_days_to_cover": 2.78, "entry_count_20d": 2, "reentry_count_20d": 1,
            "reduction_count_20d": 15, "threshold_exit_count_20d": 1,
            "data_confidence": 0.75,
        },
        # 在册合計が出せない / 空売りは減少 / 可視ゼロ
        {
            "visible_short_ratio": None, "reported_in_scope_ratio": None,
            "pressure_adv20_20d": -0.30, "data_confidence": 0.4,
        },
    ]
    templates: set[str] = set()
    for state in ORDERED_STATES:
        for snapshot in snapshots:
            for holders in (holders_full, ()):
                described = explain.describe({**snapshot, "primary_state": state}, holders)
                for item in described["line_items"]:
                    templates.add(item["template"])
                    for part in item.get("parts", ()):
                        templates.add(part["template"])
                if described["caveat"]:
                    templates.add(described["caveat"])
    return templates


def _all_display_text() -> dict[str, str]:
    """後端が画面に出しうる文の全部（文 → どこ由来か）。"""

    found = {template: "short_monitor/explain.describe()" for template in _every_template()}
    for source in (_text_builder_literals(), _label_constants(), _classification_labels()):
        for text, origin in source.items():
            found.setdefault(text, origin)
    return found


def test_every_explanation_template_has_a_dictionary_entry():
    keys = _dictionary_keys()
    missing = sorted(
        f"{text}\n      ← {origin}"
        for text, origin in _all_display_text().items()
        if text not in keys
    )
    assert not missing, (
        "後端が返す表示文が辞書に無い（ja/en でも原文のまま画面に出る）:\n  "
        + "\n  ".join(missing)
    )


@pytest.mark.parametrize("locale_index, locale", [(0, "en"), (1, "ja")])
def test_entries_carry_both_english_and_japanese(locale_index, locale):
    """辞書に **あるが空** では、フォールバックで原文に戻るだけ。"""

    entries = _dictionary_entries()
    empty = sorted(
        f"{text}\n      ← {origin}"
        for text, origin in _all_display_text().items()
        if text in entries and not entries[text][locale_index].strip()
    )
    assert not empty, f"{locale} の訳文が空:\n  " + "\n  ".join(empty)


def test_the_ast_scan_actually_finds_things():
    """走査が空振りしていたら、この門は「全部合格」を返してしまう。

    `line()` の呼び出しは強度スキャンとニュースに実在するので、そこが
    0 件になったら —— 名前を変えた・約束を外れた —— 気づけるようにする。
    """

    literals = _text_builder_literals()
    assert len(literals) >= 20, f"AST 走査が {len(literals)} 件しか拾えていない"
    assert "关联上市公司" in literals
    assert "长期趋势仍未修复" in literals
