"""報告主体の分類（reporter_class）と informed 口径。

分類は **実体（名前）** で行い、`Notes` のヘッジ標注には頼らない —— 実測で
ヘッジ標注は予測力を区別できなかった（−2.02% vs −2.18%）。名簿に無い名前は
unknown で、unknown は informed に **含める**（分からないものを情報なしに倒すと
新しい運用会社が全部消える）。
"""

from app.services.short_monitor import reporters as rep


def test_japanese_script_securities_houses_are_domestic_brokers():
    """日本語表記の証券会社は、グループが海外投行でも国内法人の営業実態。"""

    assert rep.classify("モルガン・スタンレーMUFG証券株式会社", group_id="morgan-stanley") == rep.CLASS_DOMESTIC_BROKER
    assert rep.classify("野村證券株式会社", group_id="nomura") == rep.CLASS_DOMESTIC_BROKER
    assert rep.classify("ＳＭＢＣ日興証券株式会社", group_id="smbc") == rep.CLASS_DOMESTIC_BROKER
    assert rep.classify("三菱ＵＦＪモルガン・スタンレー証券株式会社") == rep.CLASS_DOMESTIC_BROKER


def test_global_bank_entities_are_prime_brokers():
    assert rep.classify("Nomura International plc", group_id="nomura") == rep.CLASS_GLOBAL_PB
    assert rep.classify("UBS AG", group_id="ubs") == rep.CLASS_GLOBAL_PB
    # 英語表記の日本法人（JPM Securities Japan）は実測 −2.97%: 国内証券ではない
    assert rep.classify("JPM Securities Japan Co Ltd.", group_id="jpmorgan") == rep.CLASS_GLOBAL_PB
    assert rep.classify("MERRILL LYNCH INTERNATIONAL") == rep.CLASS_GLOBAL_PB
    assert rep.classify("BNP Paribas Arbitrage SNC") == rep.CLASS_GLOBAL_PB


def test_market_makers_and_hedge_funds_are_recognised():
    assert rep.classify("XTX Markets Pte Ltd") == rep.CLASS_MARKET_MAKER
    assert rep.classify("Jane Street Asia Trading Limited") == rep.CLASS_MARKET_MAKER
    assert rep.classify("Jump Trading Pacific Pte Ltd") == rep.CLASS_MARKET_MAKER
    assert rep.classify("Integrated Core Strategies (Asia) Pte. Ltd.") == rep.CLASS_HEDGE_FUND
    assert rep.classify("Qube Research & Technologies Limited") == rep.CLASS_HEDGE_FUND
    assert rep.classify("OXAM QUANT FUND LIMITED") == rep.CLASS_HEDGE_FUND


def test_aggregates_and_unknowns():
    assert rep.classify("個人", is_aggregate=True) == rep.CLASS_AGGREGATE
    assert rep.classify("個人") == rep.CLASS_AGGREGATE
    assert rep.classify("Alpha Partners") == rep.CLASS_UNKNOWN
    assert rep.classify("") == rep.CLASS_AGGREGATE


def test_informed_excludes_only_aggregates():
    """クラス単位の校正（2026-09-02）: domestic_broker −2.15% は global_pb −2.27% と
    同水準。外してよいと実測が言うのは aggregate（個人 −0.39%）だけ。"""

    assert rep.is_informed(rep.CLASS_GLOBAL_PB)
    assert rep.is_informed(rep.CLASS_DOMESTIC_BROKER)
    assert rep.is_informed(rep.CLASS_HEDGE_FUND)
    assert rep.is_informed(rep.CLASS_MARKET_MAKER)
    assert rep.is_informed(rep.CLASS_UNKNOWN)
    assert rep.is_informed(None)
    assert not rep.is_informed(rep.CLASS_AGGREGATE)


def test_classify_events_is_keyed_by_legal_id_and_counts_classes():
    events = [
        {"legal_id": "nomura-international", "raw_holder_name": "Nomura International plc", "group_id": "nomura"},
        {"legal_id": "nomura-international", "raw_holder_name": "NOMURA INTERNATIONAL PLC", "group_id": "nomura"},
        {"legal_id": "野村證券", "raw_holder_name": "野村證券株式会社", "group_id": "nomura"},
        {"legal_id": "aggregate-個人", "raw_holder_name": "個人", "group_id": None},
    ]
    classes = rep.classify_events(events)
    assert classes == {
        "nomura-international": rep.CLASS_GLOBAL_PB,
        "野村證券": rep.CLASS_DOMESTIC_BROKER,
        "aggregate-個人": rep.CLASS_AGGREGATE,
    }
    assert rep.class_counts(classes, classes.keys()) == {
        rep.CLASS_GLOBAL_PB: 1, rep.CLASS_DOMESTIC_BROKER: 1, rep.CLASS_AGGREGATE: 1,
    }
    assert rep.REPORTER_VERSION == "rep-v2"
