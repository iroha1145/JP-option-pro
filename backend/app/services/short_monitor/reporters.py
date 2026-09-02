"""報告主体の分類（reporter_class）。

空売り残高報告の **報告主体 ≠ 判断主体**。報告量の上位はほぼ投行・証券で、
その建玉には (a) prime brokerage で顧客ヘッジファンドの方向性ポジションを
自社名義で報告しているもの、(b) 自社の派生商品・貸株・CB のヘッジ、が混ざる。
2026-09-02 の実測（2023-06〜、66 万イベント、公開翌営業日終値→20 営業日
の対 TOPIX 超過中位）:

    実体別（標本 >=150 の 48 実体）: p10 −3.71% … p90 +0.33% —— 4 ポイントの差
      Nomura Intl −2.97 / UBS −2.92 / JPM −2.97 / XTX −3.71 / Jane Street −3.64
      野村證券 −0.33 / 三菱UFJMS証券 −0.68 / SMBC日興 +0.67 / 個人 −0.39
    `Notes` の「ヘッジ」明記        区別できない（−2.02 vs −2.18）

**クラス単位では差が出なかった**（同日、`app.research.informedness` で校正）:

    global_pb −2.27% (n 233,745) / market_maker −2.19% (4,949) / domestic_broker −2.15% (66,949)
    unknown −1.85% (3,500) / hedge_fund −1.03% (14,188) / aggregate −0.39% (2,218)

「日本語表記の国内証券は情報が薄い」という仮説は、名前の挙がった 3 社には
当たるが、クラス全体には当たらない —— モルガン・スタンレーMUFG証券（27.6 万件）
が国内証券クラスの大半を占め、その中位は海外 PB と同じ水準。差は **実体単位**
にあって、クラス単位には無い。

したがって `INFORMED_CLASSES` から外すのは、実測で明確に薄かった `aggregate`
（個人 など複数の別人の集合）だけ。クラスは記述・検証用のメタデータとして
残し、情報量の重み付けは実体単位（`informedness` の滚动・様本外）で行う。
分類は人手で維持する初期値で、ここに無い名前は `unknown` —— 推測で埋めない。

因子側は全鎖の口径（`pressure_all`）と informed 口径（`pressure_informed`）を
**両方** 出し、検証で別々に評価する。
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from .institutions import normalize_name

#: 分類規則の版。名簿や規則を変えたら上げる（スナップショット版に載る）。
#: v2: INFORMED_CLASSES から domestic_broker を戻す（クラス単位の校正で差が
#:     出なかった: −2.15% vs global_pb −2.27%）。外すのは aggregate だけ。
REPORTER_VERSION = "rep-v2"

CLASS_GLOBAL_PB = "global_pb"            # 海外投行 / プライムブローカー名義
CLASS_DOMESTIC_BROKER = "domestic_broker"  # 日本語表記の国内証券会社
CLASS_HEDGE_FUND = "hedge_fund"          # 方向性の運用主体
CLASS_MARKET_MAKER = "market_maker"      # クオンツ・マーケットメイカー
CLASS_AGGREGATE = "aggregate"            # 個人 など、複数の別人の集合
CLASS_UNKNOWN = "unknown"

ALL_CLASSES = (
    CLASS_GLOBAL_PB, CLASS_DOMESTIC_BROKER, CLASS_HEDGE_FUND,
    CLASS_MARKET_MAKER, CLASS_AGGREGATE, CLASS_UNKNOWN,
)

#: 方向性の情報を含むとみなすクラス。**unknown は入れる**（分からないものを
#: 「情報なし」に倒すと、名簿に無い新しい運用会社が全部消える）。
#: 外すのは、クラス単位の校正で明確に薄かった集合名義（個人 −0.39%）だけ。
#: domestic_broker は v1 で外していたが、クラス全体では −2.15%（海外 PB と同水準）
#: だったので v2 で戻した —— 差は実体単位にあり、クラス単位には無い。
INFORMED_CLASSES = frozenset({
    CLASS_GLOBAL_PB, CLASS_DOMESTIC_BROKER, CLASS_HEDGE_FUND, CLASS_MARKET_MAKER, CLASS_UNKNOWN,
})

#: グローバル投行のグループ（institutions._GROUP_RULES の group_id）。
_BANK_GROUPS = frozenset({
    "morgan-stanley", "goldman-sachs", "barclays", "nomura", "bofa", "jpmorgan",
    "ubs", "citi", "bnp-paribas", "daiwa", "mizuho", "smbc", "deutsche-bank",
    "societe-generale", "jefferies", "macquarie", "hsbc",
})

#: 正規化名（casefold・記号除去済み）に対する部分一致。
_MARKET_MAKER_NEEDLES = (
    "xtx", "jane street", "jump trading", "citadel securities", "optiver",
    "susquehanna", "flow traders", "hudson river", "tower research", "virtu",
    "imc trading", "drw ", "maven securities", "quantlab", "headlands",
)
_HEDGE_FUND_NEEDLES = (
    "millennium", "integrated core strategies", "marshall wace", "qube research",
    "point72", "citadel advisors", "citadel europe", "man solutions", "glg partners",
    "two sigma", "arrowstreet", "segantii", "dymon", "oxam", "oxford asset",
    "numeric investors", "aqr", "d e shaw", "renaissance technologies", "balyasny",
    "schonfeld", "exoduspoint", "brevan howard", "capula", "elliott", "third point",
    "tiger global", "coatue", "viking global", "lone pine", "maverick capital",
    "kadensa", "greenlight", "ako capital", "egerton", "lansdowne", "sculptor",
    "och ziff", "engadine", "pinpoint", "polymer capital", "tybourne", "gsa capital",
    "squarepoint", "eisler", "verition", "walleye", "hbk", "lmr partners",
)
#: 日本語表記の証券会社。normalize_name は「株式会社」を剥がすので「証券」で判る。
_DOMESTIC_BROKER_NEEDLES = ("証券", "證券")
#: 法人格語は normalize_name で消えるので、原表記（casefold）に対して見る。
_BANK_WORDS = (
    "bank", "securities", "capital markets", "international", "arbitrage",
    "merrill lynch", "j p morgan", "jpm ", "morgan stanley", "goldman sachs",
)
_AGGREGATE_NAMES = frozenset({"個人", "individual", "individuals", "その他", "other"})


def classify(
    raw_name: str | None, *, group_id: str | None = None, is_aggregate: bool = False
) -> str:
    """生表記 → reporter_class。名簿に無ければ `unknown`。"""

    raw = (raw_name or "").strip()
    normalized = normalize_name(raw)
    if is_aggregate or not normalized or normalized in _AGGREGATE_NAMES or raw in _AGGREGATE_NAMES:
        return CLASS_AGGREGATE
    if any(needle in normalized for needle in _MARKET_MAKER_NEEDLES):
        return CLASS_MARKET_MAKER
    if any(needle in normalized for needle in _HEDGE_FUND_NEEDLES):
        return CLASS_HEDGE_FUND
    # 日本語表記の証券会社。国内法人の営業実態（派生商品・貸株・CB のヘッジ）
    # を映すという仮説で分けたが、クラス単位では海外 PB と差が出なかった。
    # 記述・実体別校正のためのメタデータとして残す。
    if any(needle in normalized for needle in _DOMESTIC_BROKER_NEEDLES):
        return CLASS_DOMESTIC_BROKER
    lowered = raw.casefold()
    if group_id in _BANK_GROUPS or any(word in lowered for word in _BANK_WORDS):
        return CLASS_GLOBAL_PB
    return CLASS_UNKNOWN


def is_informed(reporter_class: str | None) -> bool:
    return (reporter_class or CLASS_UNKNOWN) in INFORMED_CLASSES


def classify_events(events: Iterable[Mapping[str, Any]]) -> dict[str, str]:
    """イベント列 → {legal_id: reporter_class}。同じ legal_id は 1 度だけ判定する。"""

    out: dict[str, str] = {}
    for event in events:
        legal_id = str(event.get("legal_id") or "")
        if not legal_id or legal_id in out:
            continue
        out[legal_id] = classify(
            event.get("raw_holder_name"),
            group_id=event.get("group_id"),
            is_aggregate=legal_id.startswith("aggregate-"),
        )
    return out


def class_counts(classes: Mapping[str, str], legal_ids: Iterable[str]) -> dict[str, int]:
    """機関別状態の集合を、クラスごとの件数に畳む（表示・検証用）。"""

    counts: dict[str, int] = {}
    for legal_id in legal_ids:
        name = classes.get(legal_id, CLASS_UNKNOWN)
        counts[name] = counts.get(name, 0) + 1
    return counts


__all__ = [
    "ALL_CLASSES",
    "CLASS_AGGREGATE",
    "CLASS_DOMESTIC_BROKER",
    "CLASS_GLOBAL_PB",
    "CLASS_HEDGE_FUND",
    "CLASS_MARKET_MAKER",
    "CLASS_UNKNOWN",
    "INFORMED_CLASSES",
    "REPORTER_VERSION",
    "class_counts",
    "classify",
    "classify_events",
    "is_informed",
]
