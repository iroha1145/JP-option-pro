"""ニュースの決定論的分類と重要度スコア（モデル前段のルール層）。

分類は日本株のイベント語彙で行う。重要度は説明可能なコンポーネント加重
平均で、欠損コンポーネントは重みごと外す（中立値で埋めない）。
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

CLASSIFIER_VERSION = "jp-news-rules-v1"

# カテゴリ → (日本語キーワード, 英語キーワード)
CATEGORY_RULES: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    ("決算", ("決算", "四半期", "通期", "決算短信", "営業益", "経常益", "最終益", "営業利益", "純利益"), ("earnings", "quarterly results", "fiscal year results")),
    ("業績予想修正", ("上方修正", "下方修正", "業績予想", "予想を修正", "見通しを引き上げ", "見通しを引き下げ"), ("raises guidance", "cuts guidance", "revises forecast", "upward revision", "downward revision")),
    ("配当", ("増配", "減配", "配当予想", "復配", "無配", "記念配当", "配当方針"), ("dividend",)),
    ("自社株買い", ("自社株買い", "自己株式の取得", "自己株式取得", "自社株取得"), ("share buyback", "share repurchase", "buyback")),
    ("株式分割", ("株式分割", "株式併合"), ("stock split", "share consolidation")),
    ("増資・資金調達", ("公募増資", "第三者割当", "新株予約権", "転換社債", "資金調達", "起債", "社債発行"), ("share offering", "capital raise", "convertible bond")),
    ("M&A・TOB", ("TOB", "公開買付", "買収", "合併", "経営統合", "子会社化", "MBO", "株式交換", "資本提携"), ("acquisition", "merger", "tender offer", "takeover", "buyout")),
    ("大口受注", ("受注", "大型契約", "契約締結", "供給契約", "採用決定"), ("contract win", "order", "supply agreement")),
    ("製品・技術", ("新製品", "新技術", "開発", "量産", "特許", "実用化", "発売"), ("launches", "develops", "patent", "mass production")),
    ("供給網", ("サプライチェーン", "部材", "調達", "供給不足", "工場", "生産停止", "操業"), ("supply chain", "shortage", "factory", "production halt")),
    ("規制・政策", ("規制", "認可", "承認", "法改正", "経済産業省", "厚労省", "政府", "補助金", "制裁"), ("regulation", "approval", "government", "subsidy", "sanction")),
    ("ガバナンス", ("ガバナンス", "不適切", "内部統制", "株主提案", "アクティビスト", "社外取締役"), ("governance", "activist", "shareholder proposal")),
    ("人事", ("社長", "代表取締役", "人事", "就任", "辞任", "退任", "CEO交代"), ("appoints", "resigns", "CEO change")),
    ("事故・訴訟", ("事故", "訴訟", "提訴", "リコール", "不正", "データ改ざん", "火災", "情報漏えい"), ("lawsuit", "recall", "accident", "fraud", "data breach")),
    ("為替", ("円安", "円高", "為替", "ドル円"), ("yen", "usd/jpy", "currency")),
    ("日銀・金利", ("日銀", "日本銀行", "金融政策決定会合", "利上げ", "利下げ", "国債買い入れ", "金利", "YCC"), ("bank of japan", "boj", "rate hike", "rate cut", "monetary policy")),
    ("業界景況", ("業界", "市況", "需要", "景気", "統計", "出荷", "販売台数"), ("industry", "demand", "shipments")),
    ("信用・空売り", ("信用規制", "空売り", "貸借", "日々公表", "増担保"), ("short selling", "margin regulation")),
)

CATEGORY_WEIGHTS: dict[str, float] = {
    "業績予想修正": 95.0, "M&A・TOB": 95.0, "決算": 85.0, "自社株買い": 85.0,
    "増資・資金調達": 80.0, "配当": 75.0, "大口受注": 75.0, "株式分割": 70.0,
    "事故・訴訟": 70.0, "規制・政策": 60.0, "日銀・金利": 60.0, "人事": 50.0,
    "製品・技術": 55.0, "供給網": 55.0, "ガバナンス": 55.0, "為替": 45.0,
    "業界景況": 40.0, "信用・空売り": 55.0, "その他": 25.0,
}


def normalize_text(text: str) -> str:
    return unicodedata.normalize("NFKC", text or "").strip()


def classify(title: str, summary: str | None) -> list[str]:
    haystack = normalize_text(f"{title} {summary or ''}").lower()
    categories: list[str] = []
    for name, needles_ja, needles_en in CATEGORY_RULES:
        if any(needle.lower() in haystack for needle in (*needles_ja, *needles_en)):
            categories.append(name)
    return categories or ["その他"]


def detect_language(title: str, summary: str | None) -> str:
    text = f"{title}{summary or ''}"
    kana = sum(1 for ch in text if "぀" <= ch <= "ヿ")
    cjk = sum(1 for ch in text if "一" <= ch <= "鿿")
    ascii_letters = sum(1 for ch in text if ch.isascii() and ch.isalpha())
    if kana >= 2 or (cjk >= 4 and kana >= 1):
        return "ja"
    if cjk >= 4 and kana == 0:
        return "zh_or_ja"  # 漢字のみ: 判定保留（見出しのみ等）
    if ascii_letters > max(cjk, kana) * 3 and ascii_letters >= 10:
        return "en"
    return "unknown"


_WORD_RE = re.compile(r"[a-z0-9]+")


def title_bigrams(title: str) -> frozenset[str]:
    normalized = normalize_text(title).lower()
    ascii_tokens = set(_WORD_RE.findall(normalized))
    cjk_chars = [ch for ch in normalized if not ch.isascii() and not ch.isspace()]
    bigrams = {a + b for a, b in zip(cjk_chars, cjk_chars[1:])} if len(cjk_chars) >= 2 else set(cjk_chars)
    return frozenset(ascii_tokens | bigrams)


def titles_similar(a: frozenset[str], b: frozenset[str], *, threshold: float = 0.5) -> bool:
    """同一イベントの別ソース報道判定（Jaccard）。"""

    if not a or not b:
        return False
    union = len(a | b)
    if union == 0:
        return False
    return len(a & b) / union >= threshold


def content_fingerprint(title: str, published_at: str | None, securities: Sequence[str]) -> str:
    """近接重複の指紋: 正規化タイトルの文字 2-gram + 日付バケット + 実体。"""

    normalized = normalize_text(title).lower()
    ascii_tokens = set(_WORD_RE.findall(normalized))
    cjk_chars = [ch for ch in normalized if not ch.isascii() and not ch.isspace()]
    bigrams = {a + b for a, b in zip(cjk_chars, cjk_chars[1:])} if len(cjk_chars) >= 2 else set(cjk_chars)
    date_bucket = (published_at or "")[:10]
    payload = "|".join(
        (
            ",".join(sorted(ascii_tokens | bigrams))[:2000],
            date_bucket,
            ",".join(sorted(securities)),
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def news_identity(source: str, url: str | None, title: str) -> str:
    payload = f"{source}|{url or ''}|{normalize_text(title)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def market_relevance(
    categories: Sequence[str], securities: Sequence[Mapping[str, Any]]
) -> str | None:
    """日本株との関連: 個別銘柄 / 業種・市場 / 対象外(None)。

    実体も市場カテゴリも無い記事は日本株フィードに入れない。
    """

    if securities:
        return "security"
    market_level = {"日銀・金利", "為替", "規制・政策", "業界景況", "信用・空売り"}
    if any(category in market_level for category in categories):
        return "market"
    return None


def importance_score(
    *,
    categories: Sequence[str],
    securities_count: int,
    published_at: str | None,
    in_watchlist: bool,
    has_radar_event: bool,
    now: datetime | None = None,
) -> tuple[float | None, dict[str, Any], list[str]]:
    components: dict[str, float] = {}
    reasons: list[str] = []

    category_score = max((CATEGORY_WEIGHTS.get(c, 30.0) for c in categories), default=None)
    if category_score is not None:
        components["category"] = category_score
        reasons.append(f"事件类别: {'/'.join(categories)}")

    if securities_count > 0:
        components["entity"] = min(100.0, 55.0 + 15.0 * securities_count)
        reasons.append("关联上市公司")

    if published_at:
        try:
            published = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
            age_hours = max(0.0, ((now or datetime.now(timezone.utc)) - published).total_seconds() / 3600.0)
            components["recency"] = max(0.0, 100.0 - age_hours * 1.4)
            reasons.append("发布时间较近" if age_hours < 24 else "发布已有一段时间")
        except ValueError:
            pass

    bonus = 0.0
    if in_watchlist:
        bonus += 10.0
        reasons.append("自选股相关")
    if has_radar_event:
        bonus += 8.0
        reasons.append("雷达候选相关")

    weights = {"category": 0.45, "entity": 0.25, "recency": 0.30}
    active = {key: weights[key] for key in components if key in weights}
    if not active:
        return None, {}, ["可用证据不足，未补成中性分数"]
    total_weight = sum(active.values())
    score = sum(components[key] * weight for key, weight in active.items()) / total_weight
    score = min(100.0, score + bonus)
    return round(score, 1), {**components, "bonus": bonus}, reasons


__all__ = [
    "CATEGORY_RULES",
    "CATEGORY_WEIGHTS",
    "CLASSIFIER_VERSION",
    "classify",
    "content_fingerprint",
    "detect_language",
    "importance_score",
    "market_relevance",
    "news_identity",
    "normalize_text",
]
