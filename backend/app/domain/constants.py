"""Japan equity market constants.

Codes come from the J-Quants V2 reference (marketcode / sector tables /
holiday divisions). Names for sectors arrive with the master data itself —
the tables here exist for display fallbacks and stable ordering, not as a
substitute source of truth.
"""

from __future__ import annotations

MARKET_TIMEZONE = "Asia/Tokyo"
CURRENCY = "JPY"

# 市場区分コード（現行 2022-04 以降）
MARKET_SEGMENTS: dict[str, str] = {
    "0111": "プライム",
    "0112": "スタンダード",
    "0113": "グロース",
    "0105": "TOKYO PRO MARKET",
    "0109": "その他",
}

# 旧市場区分（2022-04 以前の履歴データにのみ現れる）
LEGACY_MARKET_SEGMENTS: dict[str, str] = {
    "0101": "東証一部",
    "0102": "東証二部",
    "0104": "マザーズ",
    "0106": "JASDAQ スタンダード",
    "0107": "JASDAQ グロース",
}

PRIMARY_MARKET_CODES: tuple[str, ...] = ("0111", "0112", "0113")

# 取引カレンダー HolDiv
HOLIDAY_DIVISION_NON_BUSINESS = "0"
HOLIDAY_DIVISION_BUSINESS = "1"
HOLIDAY_DIVISION_HALF_DAY = "2"
HOLIDAY_DIVISION_HOLIDAY_TRADING = "3"  # 祝日取引（デリバティブ）— 現物は非営業
# TSE 現物株の取引日: 1（通常営業日）と 2（半日立会）。
EQUITY_TRADING_DIVISIONS: frozenset[str] = frozenset(
    {HOLIDAY_DIVISION_BUSINESS, HOLIDAY_DIVISION_HALF_DAY}
)

# 東証33業種コード（公式分類、コード順）
SECTOR33: dict[str, str] = {
    "0050": "水産・農林業",
    "1050": "鉱業",
    "2050": "建設業",
    "3050": "食料品",
    "3100": "繊維製品",
    "3150": "パルプ・紙",
    "3200": "化学",
    "3250": "医薬品",
    "3300": "石油・石炭製品",
    "3350": "ゴム製品",
    "3400": "ガラス・土石製品",
    "3450": "鉄鋼",
    "3500": "非鉄金属",
    "3550": "金属製品",
    "3600": "機械",
    "3650": "電気機器",
    "3700": "輸送用機器",
    "3750": "精密機器",
    "3800": "その他製品",
    "4050": "電気・ガス業",
    "5050": "陸運業",
    "5100": "海運業",
    "5150": "空運業",
    "5200": "倉庫・運輸関連業",
    "5250": "情報・通信業",
    "6050": "卸売業",
    "6100": "小売業",
    "7050": "銀行業",
    "7100": "証券、商品先物取引業",
    "7150": "保険業",
    "7200": "その他金融業",
    "8050": "不動産業",
    "9050": "サービス業",
    "9999": "その他",
}

# 主要指数コード（J-Quants /indices/bars/daily）
INDEX_CODES: dict[str, str] = {
    "0000": "TOPIX",
    "0500": "東証プライム市場指数",
    "0501": "東証スタンダード市場指数",
    "0502": "東証グロース市場指数",
    "0028": "TOPIX Core30",
    "0029": "TOPIX Large70",
    "002A": "TOPIX 100",
    "002B": "TOPIX Mid400",
    "002C": "TOPIX 500",
    "002D": "TOPIX Small",
    "0075": "東証REIT指数",
    "8100": "TOPIX バリュー",
    "8200": "TOPIX グロース",
}

# ホームの指数タープに並べる既定セット（表示順）
HOME_INDEX_CODES: tuple[str, ...] = ("0000", "0500", "0501", "0502", "0028", "002D")

TOPIX_INDEX_CODE = "0000"

# 信用区分（IssType / Mrgn）
MARGIN_ISSUE_TYPES: dict[str, str] = {
    "1": "信用銘柄",
    "2": "貸借銘柄",
    "3": "その他",
}

__all__ = [
    "CURRENCY",
    "EQUITY_TRADING_DIVISIONS",
    "HOLIDAY_DIVISION_BUSINESS",
    "HOLIDAY_DIVISION_HALF_DAY",
    "HOLIDAY_DIVISION_HOLIDAY_TRADING",
    "HOLIDAY_DIVISION_NON_BUSINESS",
    "HOME_INDEX_CODES",
    "INDEX_CODES",
    "LEGACY_MARKET_SEGMENTS",
    "MARGIN_ISSUE_TYPES",
    "MARKET_SEGMENTS",
    "MARKET_TIMEZONE",
    "PRIMARY_MARKET_CODES",
    "SECTOR33",
    "TOPIX_INDEX_CODE",
]
