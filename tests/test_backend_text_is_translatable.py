"""バックエンドが返す表示文は、フロントの辞書に必ず載っていること。

空売りモニターの説明文はサーバ側で組み立てる（相手の言語は知らない）。
そのため **中文のテンプレートを msgid にして** 返し、置換だけフロントの
`t()` が行う —— 辞書に載っていないテンプレートは ja/en でも中文のまま
画面に出る。実際 `現在の分類` の周辺がまるごと中文で出ていた。

ここが素通しだと同じことが何度でも起きるので、
「describe() が出しうるテンプレート」⊆「辞書のキー」を機械的に確かめる。
"""

import re
from pathlib import Path

import pytest

from app.services.short_monitor import explain
from app.services.short_monitor.scoring import VALIDATION
from app.services.short_monitor.states import ORDERED_STATES

DICT_PATH = Path(__file__).resolve().parents[1] / "frontend-src/src/i18n/dict/index.ts"


def _dictionary_keys() -> set[str]:
    """辞書のキー。既存エントリは **クオート無し** の書き方も混在する。"""

    source = DICT_PATH.read_text(encoding="utf-8")
    keys: set[str] = set()
    for match in re.finditer(r"^\s*'((?:[^'\\]|\\.)*)':", source, re.MULTILINE):
        keys.add(match.group(1).replace("\\'", "'").replace("\\\\", "\\"))
    for match in re.finditer(r"^\s*([^\s'\"\[\]{}:,/][^:'\"]*?):\s*\[", source, re.MULTILINE):
        keys.add(match.group(1).strip())
    return keys


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


def test_every_explanation_template_has_a_dictionary_entry():
    keys = _dictionary_keys()
    missing = sorted(t for t in _every_template() if t not in keys)
    assert not missing, (
        "後端の説明文が辞書に無い（ja/en で中文のまま出る）:\n  "
        + "\n  ".join(missing)
    )


def test_state_labels_have_dictionary_entries():
    keys = _dictionary_keys()
    missing = sorted(label for label in explain.STATE_LABELS.values() if label not in keys)
    assert not missing, f"状態ラベルの訳が無い: {missing}"


def test_the_validation_summary_has_a_dictionary_entry():
    """検証結果の横断幕はページで一番目立つ 1 文。ここが中文のままは目立つ。"""

    assert VALIDATION["summary"] in _dictionary_keys()


@pytest.mark.parametrize("locale_index", [0, 1])
def test_entries_carry_both_english_and_japanese(locale_index):
    """辞書に **あるが空** では、フォールバックで中文に戻るだけ。"""

    source = DICT_PATH.read_text(encoding="utf-8")
    templates = _every_template() | {VALIDATION["summary"]}
    empty: list[str] = []
    for template in templates:
        escaped = re.escape(template.replace("'", "\\'"))
        match = re.search(escaped + r"':\s*\[\s*'((?:[^'\\]|\\.)*)',\s*'((?:[^'\\]|\\.)*)'",
                          source, re.DOTALL)
        if match and not match.group(locale_index + 1).strip():
            empty.append(template)
    assert not empty, f"訳文が空: {empty}"
