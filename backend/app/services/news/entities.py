"""日本株エンティティ目録: 上場マスタから別名を生成し、ニュース本文と照合。

規則:
- 照合は必ず security_id（canonical_code）へ正規化して返す。
- 4桁数字コード単独では照合しない（数字の誤マッチが多すぎる）。
  「（7203）」「(7203)」「＜7203＞」のような開示・報道の定型文脈のみ許可。
- 別名は日本語正式名・英語名・法人格/HD 接尾辞を除いた短縮名から生成。
  2文字以下の短縮名は誤爆源なので生成しない。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

_LEGAL_SUFFIXES = (
    "ホールディングス", "グループ本社", "グループ", "株式会社", "（株）", "(株)",
    "Holdings", "Group", "Inc.", "Inc", "Corp.", "Corp", "Co., Ltd.", "Co.,Ltd.",
    "Ltd.", "Ltd", "Corporation", "Company",
)

# 「（7203）」「(7203)」「＜7203＞」「<285A>」だけをコード文脈として認める。
_CODE_CONTEXT = re.compile(r"[（(＜<]\s*([0-9][0-9A-Z]{3})\s*[)）＞>]")

_KATAKANA = re.compile(r"[ァ-ヶーｦ-ﾟ]")
_KANJI = re.compile(r"[一-鿿々]")


def _is_katakana(char: str) -> bool:
    return bool(char) and bool(_KATAKANA.fullmatch(char))


def _is_kanji(char: str) -> bool:
    return bool(char) and bool(_KANJI.fullmatch(char))


def _boundary_ok(text: str, start: int, end: int, alias: str) -> bool:
    """短い日本語別名の境界検査。

    実害事例: 「ステーキング」の中の「キング」(8118)、「鈴木潤一」(人名) の
    中の「鈴木」(6785)。純カタカナ別名はカタカナ境界を、3文字以下の別名は
    漢字/カタカナ境界を許さない。長い別名（トヨタ自動車 等）は誤爆余地が
    小さいので従来通り部分一致。"""

    before = text[start - 1] if start > 0 else ""
    after = text[end] if end < len(text) else ""
    all_katakana = all(_is_katakana(char) for char in alias)
    if all_katakana:
        return not _is_katakana(before) and not _is_katakana(after)
    if len(alias) <= 3:
        blocked = (_is_kanji(before) or _is_katakana(before)) or (
            _is_kanji(after) or _is_katakana(after)
        )
        return not blocked
    return True


def _find_with_boundary(text: str, alias: str) -> bool:
    index = text.find(alias)
    while index != -1:
        if _boundary_ok(text, index, index + len(alias), alias):
            return True
        index = text.find(alias, index + 1)
    return False


def _strip_suffixes(name: str) -> str:
    text = name.strip()
    changed = True
    while changed:
        changed = False
        for suffix in _LEGAL_SUFFIXES:
            if text.endswith(suffix) and len(text) > len(suffix):
                text = text[: -len(suffix)].strip()
                changed = True
    return text


def build_alias_rows(
    securities: Iterable[Mapping[str, Any]],
    *,
    user_aliases: Mapping[str, list[str]] | None = None,
) -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    for security in securities:
        code = security.get("canonical_code")
        if not code:
            continue
        name_ja = (security.get("name_ja") or "").strip()
        name_en = (security.get("name_en") or "").strip()
        if name_ja:
            rows.append((name_ja, code, "name_ja"))
            short_ja = _strip_suffixes(name_ja)
            if short_ja and short_ja != name_ja and len(short_ja) >= 3:
                rows.append((short_ja, code, "short_ja"))
        if name_en:
            rows.append((name_en, code, "name_en"))
            short_en = _strip_suffixes(name_en)
            if short_en and short_en != name_en and len(short_en) >= 4:
                rows.append((short_en, code, "short_en"))
    for code, aliases in (user_aliases or {}).items():
        for alias in aliases:
            if alias and len(alias) >= 2:
                rows.append((alias.strip(), code, "user"))
    return rows


@dataclass(frozen=True)
class EntityMatch:
    canonical_code: str
    alias: str
    alias_type: str


class EntityMatcher:
    """素朴な最長一致サーチ。別名数千件 × 記事数百件/回で十分速い。"""

    def __init__(self, alias_rows: Iterable[Mapping[str, Any]]) -> None:
        self._aliases: list[tuple[str, str, str]] = []
        display_to_code: dict[str, str] = {}
        for row in alias_rows:
            alias = str(row.get("alias") or "")
            code = str(row.get("canonical_code") or "")
            alias_type = str(row.get("alias_type") or "")
            if not alias or not code:
                continue
            self._aliases.append((alias, code, alias_type))
            if len(code) == 5 and code.endswith("0"):
                display_to_code[code[:4]] = code
            else:
                display_to_code[code] = code
        # 長い別名を先に照合（「トヨタ自動車」が「トヨタ」より先に当たる）
        self._aliases.sort(key=lambda item: len(item[0]), reverse=True)
        self._display_to_code = display_to_code

    def match(self, text: str, *, limit: int = 8) -> list[EntityMatch]:
        if not text:
            return []
        found: dict[str, EntityMatch] = {}
        lowered = text.lower()
        for alias, code, alias_type in self._aliases:
            if code in found:
                continue
            if alias.isascii():
                # ASCII 別名は単語境界を要求（"Sony" が "Sonya" に当たらない）
                pattern = re.compile(rf"(?<![A-Za-z0-9]){re.escape(alias.lower())}(?![A-Za-z0-9])")
                if not pattern.search(lowered):
                    continue
            else:
                # 日本語別名: 短い別名はカタカナ/漢字境界を検査（キング/鈴木問題）
                if not _find_with_boundary(text, alias):
                    continue
            found[code] = EntityMatch(code, alias, alias_type)
            if len(found) >= limit:
                break
        for match_obj in _CODE_CONTEXT.finditer(text):
            display = match_obj.group(1)
            code = self._display_to_code.get(display)
            if code and code not in found:
                found[code] = EntityMatch(code, display, "code_context")
                if len(found) >= limit:
                    break
        return list(found.values())


__all__ = ["EntityMatch", "EntityMatcher", "build_alias_rows"]
