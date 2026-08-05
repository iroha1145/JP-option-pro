"""サーバが組み立てる**表示文**の持ち方。

サーバは相手の言語を知らない —— 応答は ETag で全利用者に共有されるので、
言語ごとに別の本文を返すことはできない。そこで完成した文ではなく
**テンプレート + パラメータ** を返し、置換はフロントの `t()` に任せる。
辞書は「原文そのものを msgid にする」gettext 方式なので、テンプレート文字列
がそのまま msgid になる。

なぜ f-string ではいけないか:

    warnings.append(f"ATR约{atr:.1f}%，波动风险高")   # ← 出来上がりは
    "ATR约7.3%，波动风险高"                            #    辞書のどのキーにも
                                                       #    一致しない

数値が混ざった瞬間に辞書引きが外れるので、ja/en でも中文のまま画面に出る。
`line("ATR约{atr}%，波动风险高", atr="7.3")` なら msgid は固定で、置換だけが
言語ごとに変わる。

`rendered()` は中文で置換済みの一覧を返す。**両方**返すのが約束 ——
片方だけにすると、フロントとバックのどちらかが古い間だけ画面が空になる。
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence


def line(template: str, **params: Any) -> dict[str, Any]:
    """1 行 = テンプレート + パラメータ。"""

    return {"template": template, "params": params}


def enumeration(
    template: str, parts: Sequence[Mapping[str, Any]], *, key: str, separator: str
) -> dict[str, Any]:
    """「A、B、C」のような列挙を含む 1 行。

    結合済みの文字列は辞書に載らないので、**結合前の 1 項目ずつ** を `parts`
    で渡して、つなぎ方（区切り記号）も言語側に委ねる。
    """

    return {
        "template": template,
        "params": {},
        "parts": list(parts),
        "parts_key": key,
        "parts_sep": separator,
    }


def rendered(items: Sequence[Mapping[str, Any]]) -> list[str]:
    """中文で置換済みの一覧（API 単体で読める・既存の消費者を壊さない）。"""

    out: list[str] = []
    for item in items:
        params = dict(item.get("params") or {})
        parts = item.get("parts")
        if parts:
            params[str(item.get("parts_key") or "items")] = str(
                item.get("parts_sep") or "、"
            ).join(rendered(parts))
        out.append(str(item["template"]).format(**params))
    return out


__all__ = ["enumeration", "line", "rendered"]
