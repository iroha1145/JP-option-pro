"""機関実体の正規化。

空売り残高報告の `SSName` は表記が揺れる。同じ法人が

    ``MORGAN STANLEY & CO. INTERNATIONAL PLC``
    ``Morgan Stanley & Co. International plc``

と大小文字違いで出てくることもあれば、**別法人**が

    ``モルガン・スタンレーMUFG証券株式会社``   （日本の証券会社）
    ``Morgan Stanley & Co. International plc``  （英国法人）

のように「同じグループだが別の法的主体」として並ぶこともある。

方針は 1 つだけ:

    **名前が似ているというだけでは統合しない。**

統合が起きるのは 2 通りだけ —— (1) 正規化（NFKC・大小文字・法人格語・
記号）で **完全に一致** したとき、(2) 人手で維持する別名表に載っているとき。
それ以外は初出の実体として単独で立てる。似ているから同じだろう、はやらない。

グループ（`institution_group`）は表示と集計のための **別レイヤー**で、
イベントの法的主体を書き換えない。「モルガン・スタンレーグループ」で
まとめて見ることはできるが、下の行は日本法人と英国法人のまま残る。

`個人` のような表記は法人名ではなく **複数の別人の集合**なので、1 つの
実体として扱うと数を誤る。`is_aggregate` を立てて信頼度を下げる。
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

#: 実体解決の版。別名表や正規化規則を変えたらここを上げる（イベントに載る）。
#: v2: 正規化で剥がすのを **法人形式語だけ** に絞る。`International` /
#:     `Securities` / `Capital` / `Markets` / `証券` などは営業実態を表す語で、
#:     別法人を区別する本体の一部 —— v1 はこれも剥がしていたため
#:     `Barclays Capital Securities Ltd` が `barclays` まで潰れ、
#:     `Morgan Stanley & Co. International plc`（英国）と
#:     `Morgan Stanley & Co. LLC`（米国）が同一実体に化けた。
#:     加えて、同じ正規化名に複数の住所が観測された場合は住所で実体を分ける。
#: v3: slug が ASCII 以外を捨てていたため、三菱UFJ信託 / 三菱UFJ証券 /
#:     SBI証券 / SBIホールディングス などが同一 legal_id に潰れ、
#:     last_known の合算が大手を二重計上していた。Unicode の語を残す。
#: v4: 住所の指紋で実体を分けるのをやめる（`InstitutionResolver` の説明を参照）。
#:     分けるのは、同じ銘柄・同じ仓位日に住所違いで違う値が出た組だけ。
INSTITUTION_VERSION = "inst-v4"

MATCH_EXACT = "exact"          # この実体に属する生表記が 1 つだけ（統合していない）
MATCH_NORMALIZED = "normalized"  # 正規化で別の生表記と一致した
MATCH_CURATED = "curated"      # 人手の別名表
MATCH_AGGREGATE = "aggregate"  # 法人ではなく集合（個人 など）

#: **法人形式語だけ** を正規化で落とす。`International` / `Securities` /
#: `Capital` / `Markets` / `Holdings` / `Group` / `証券` / `銀行` / `信託` は
#: 落とさない —— これらは営業実態の記述で、別の法的主体を区別する本体の
#: 一部（`Morgan Stanley & Co. International plc` ≠ `Morgan Stanley & Co. LLC`）。
#: ASCII の語は語境界を要求する（"limited" が "unlimited" の一部を食わない
#: ように）。日本語には語境界が無いので、そのまま末尾一致で剥がす。
_LEGAL_SUFFIXES_ASCII = (
    "limited liability partnership", "limited partnership",
    "incorporated", "corporation", "company", "limited",
    "co ltd", "pte ltd", "pte", "llp", "llc", "lp", "ltd", "plc", "inc",
    "sa", "nv", "ag", "snc", "gmbh", "spa", "bv", "kk",
)
_LEGAL_SUFFIXES_CJK = (
    "投資事業有限責任組合", "株式会社", "有限会社", "合同会社",
)

#: 実体ではなく集合を指す表記。
_AGGREGATE_NAMES = frozenset({"個人", "individual", "individuals", "その他", "other"})

#: 人手で維持するグループ表。**正規化後の名前に対する前方一致**で当てる。
#: ここに無いものはグループ無し（`group_id = None`）。推測で埋めない。
_GROUP_RULES: tuple[tuple[str, str, str], ...] = (
    ("morgan stanley", "morgan-stanley", "モルガン・スタンレー"),
    ("モルガン スタンレー", "morgan-stanley", "モルガン・スタンレー"),
    ("三菱ufjモルガン スタンレー", "morgan-stanley", "モルガン・スタンレー"),
    ("goldman sachs", "goldman-sachs", "ゴールドマン・サックス"),
    ("ゴールドマン サックス", "goldman-sachs", "ゴールドマン・サックス"),
    ("barclays", "barclays", "バークレイズ"),
    ("バークレイズ", "barclays", "バークレイズ"),
    ("nomura", "nomura", "野村"),
    ("野村", "nomura", "野村"),
    ("merrill lynch", "bofa", "バンク・オブ・アメリカ"),
    ("bofa", "bofa", "バンク・オブ・アメリカ"),
    ("bank of america", "bofa", "バンク・オブ・アメリカ"),
    ("jpm", "jpmorgan", "JPモルガン"),
    ("j p morgan", "jpmorgan", "JPモルガン"),
    ("jpmorgan", "jpmorgan", "JPモルガン"),
    ("ジェーピーモルガン", "jpmorgan", "JPモルガン"),
    ("ubs", "ubs", "UBS"),
    ("citigroup", "citi", "シティグループ"),
    ("citibank", "citi", "シティグループ"),
    ("シティグループ", "citi", "シティグループ"),
    ("bnp paribas", "bnp-paribas", "BNPパリバ"),
    ("ビーエヌピー パリバ", "bnp-paribas", "BNPパリバ"),
    ("daiwa", "daiwa", "大和"),
    ("大和", "daiwa", "大和"),
    ("mizuho", "mizuho", "みずほ"),
    ("みずほ", "mizuho", "みずほ"),
    ("smbc", "smbc", "三井住友"),
    ("三井住友", "smbc", "三井住友"),
    ("credit suisse", "ubs", "UBS"),      # 2023 統合。旧名は同一グループへ寄せる
    ("deutsche", "deutsche-bank", "ドイツ銀行"),
    ("societe generale", "societe-generale", "ソシエテ・ジェネラル"),
    ("jefferies", "jefferies", "ジェフリーズ"),
    ("macquarie", "macquarie", "マッコーリー"),
    ("hsbc", "hsbc", "HSBC"),
    ("jane street", "jane-street", "ジェーン・ストリート"),
    ("jump trading", "jump-trading", "ジャンプ・トレーディング"),
    ("qube research", "qube", "Qube Research"),
    ("man ", "man-group", "マン・グループ"),
    ("millennium", "millennium", "ミレニアム"),
    ("point72", "point72", "Point72"),
    ("citadel", "citadel", "シタデル"),
    ("two sigma", "two-sigma", "Two Sigma"),
    ("arrowstreet", "arrowstreet", "Arrowstreet"),
    ("marshall wace", "marshall-wace", "Marshall Wace"),
    ("segantii", "segantii", "Segantii"),
    ("pag ", "pag", "PAG"),
    ("dymon", "dymon-asia", "Dymon Asia"),
)

_PUNCT = re.compile(r"[.,'`\"()\[\]{}/\\|:;!?&+*^%$#@~_\-–—・･,、。]")
_SPACES = re.compile(r"\s+")


def normalize_name(raw: str | None) -> str:
    """表記の揺れだけを落とす。意味のある違いは残す。

    NFKC で全角英数と半角を揃え、記号を空白にし、法人格語を末尾から剥がす。
    ここで落としてよいのは **同じ法人を指すことが確実な差** だけ。
    """

    if not raw:
        return ""
    text = unicodedata.normalize("NFKC", str(raw)).strip().casefold()
    text = _PUNCT.sub(" ", text)
    text = _SPACES.sub(" ", text).strip()
    # 法人格語は末尾側から繰り返し剥がす（"co ltd" と "ltd" の二重表記に対応）
    changed = True
    while changed and text:
        changed = False
        for suffix in _LEGAL_SUFFIXES_ASCII:
            if text.endswith(" " + suffix):
                text = text[: -(len(suffix) + 1)].strip()
                changed = True
        for suffix in _LEGAL_SUFFIXES_CJK:
            if text.endswith(suffix) and len(text) > len(suffix):
                text = text[: -len(suffix)].strip()
                changed = True
    return _SPACES.sub(" ", text).strip()


def _slug(normalized: str) -> str:
    # Unicode の語（漢字・かな）を残す。ASCII だけ残すと UFJ / SBI / SMBC
    # を共有する別法人が 1 つの legal_id に潰れる。
    slug = re.sub(r"[^\w]+", "-", normalized, flags=re.UNICODE).strip("-")
    if slug:
        return slug[:64]
    # 記号だけの名前は安定したハッシュに落とす。
    import hashlib

    return "jp-" + hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:16]


def _group_for(normalized: str) -> tuple[str | None, str | None]:
    for needle, group_id, group_name in _GROUP_RULES:
        if normalized.startswith(needle) or f" {needle}" in f" {normalized}":
            return group_id, group_name
    return None, None


@dataclass(frozen=True)
class InstitutionMapping:
    legal_id: str
    display_name: str
    normalized_name: str
    group_id: str | None
    group_name: str | None
    match_kind: str
    confidence: float
    is_aggregate: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "legal_id": self.legal_id,
            "display_name": self.display_name,
            "normalized_name": self.normalized_name,
            "group_id": self.group_id,
            "group_name": self.group_name,
            "match_kind": self.match_kind,
            "confidence": self.confidence,
            "is_aggregate": self.is_aggregate,
        }


def normalize_address(raw: str | None) -> str:
    """住所の表記揺れだけを落とす（NFKC・大小文字・記号・空白）。"""

    if not raw:
        return ""
    text = unicodedata.normalize("NFKC", str(raw)).strip().casefold()
    text = _PUNCT.sub(" ", text)
    return _SPACES.sub(" ", text).strip()


class InstitutionResolver:
    """生の表記 → 法的実体。**似ているだけでは統合しない。**

    同じ正規化名に複数の生表記が集まったときだけ「統合した」ことになるので、
    そのときに限って信頼度を下げる（統合が誤りうるのはその場合だけ）。

    **住所では実体を分けない（v4）。** v3 は「同じ正規化名に複数の住所が
    観測された名前」を住所の指紋で別実体にしていたが、本番 10 年分の実測では
    その 87 名・17,024 組（銘柄 × 名前 × ファンド）のうち、同じ仓位日に
    **違う値** を報告していた（= 本当に別法人が並行していた）のは 1 組 1 日
    だけで、同値の重複は 11,491 日あった —— 住所の違いはほぼ全部が表記揺れ・
    移転・「住所欄が空の配信」だった。分けた結果、住所欄の無い期間
    （2025-06〜2026-07 の一括配信）の連鎖が `-noaddr` という別実体になり、
    住所つき配信に切り替わった後も 7 月末の値のまま「報告義務中」として合計に
    残り続けた（2026-11-20 時点で 1,133 銘柄の合計が誤り、全体の約 4 割が
    重複または既に閾値を割った建玉）。

    本当に並行している同名別法人は、**その銘柄の中で証拠があるときだけ**
    分ける: `events.build_events` が「同じ仓位日に住所違いで違う値」を
    見つけた組に限って `split_by_address=True` で呼ぶ。
    """

    #: 正規化で統合が起きたときの信頼度。統合していなければ 1.0。
    MERGED_CONFIDENCE = 0.75
    #: 法人ではなく集合（個人 など）。1 つの実体として数えてはいけない。
    AGGREGATE_CONFIDENCE = 0.35

    def __init__(self, curated: dict[str, str] | None = None) -> None:
        # raw_name → legal_id の人手マッピング（DB の institution_aliases 由来）
        self._curated = dict(curated or {})
        self._raw_by_legal: dict[str, set[str]] = {}
        self._display_by_legal: dict[str, str] = {}

    def resolve(
        self, raw_name: str | None, address: str | None = None, *, split_by_address: bool = False,
    ) -> InstitutionMapping:
        raw = (raw_name or "").strip()
        normalized = normalize_name(raw)
        if not normalized:
            return InstitutionMapping(
                legal_id="unknown", display_name=raw or "(不明)", normalized_name="",
                group_id=None, group_name=None, match_kind=MATCH_AGGREGATE,
                confidence=0.0, is_aggregate=True,
            )

        if normalized in _AGGREGATE_NAMES or raw in _AGGREGATE_NAMES:
            legal_id = "aggregate-" + _slug(normalized)
            self._remember(legal_id, raw)
            return InstitutionMapping(
                legal_id=legal_id, display_name=raw, normalized_name=normalized,
                group_id=None, group_name=None, match_kind=MATCH_AGGREGATE,
                confidence=self.AGGREGATE_CONFIDENCE, is_aggregate=True,
            )

        curated_id = self._curated.get(raw)
        legal_id = curated_id or _slug(normalized)
        if not curated_id and split_by_address:
            cleaned = normalize_address(address)
            if cleaned:
                import hashlib

                legal_id = f"{legal_id}-a{hashlib.sha1(cleaned.encode('utf-8')).hexdigest()[:8]}"
        group_id, group_name = _group_for(normalized)
        self._remember(legal_id, raw)

        merged = len(self._raw_by_legal.get(legal_id, ())) > 1
        if curated_id:
            kind, confidence = MATCH_CURATED, 1.0
        elif merged:
            kind, confidence = MATCH_NORMALIZED, self.MERGED_CONFIDENCE
        else:
            kind, confidence = MATCH_EXACT, 1.0

        return InstitutionMapping(
            legal_id=legal_id,
            display_name=self._display_by_legal.get(legal_id, raw),
            normalized_name=normalized,
            group_id=group_id, group_name=group_name,
            match_kind=kind, confidence=confidence, is_aggregate=False,
        )

    def raw_names_for(self, legal_id: str) -> set[str]:
        return set(self._raw_by_legal.get(legal_id, ()))

    def _remember(self, legal_id: str, raw: str) -> None:
        names = self._raw_by_legal.setdefault(legal_id, set())
        names.add(raw)
        # 表示名は最初に見た表記を保つ（別名が増えても画面上の名前が揺れない）
        self._display_by_legal.setdefault(legal_id, raw)


__all__ = [
    "INSTITUTION_VERSION",
    "InstitutionMapping",
    "InstitutionResolver",
    "MATCH_AGGREGATE",
    "MATCH_CURATED",
    "MATCH_EXACT",
    "MATCH_NORMALIZED",
    "normalize_address",
    "normalize_name",
]
