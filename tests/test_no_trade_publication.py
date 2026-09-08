"""Explicit J-Quants no-trade rows are exclusions, never yesterday's prices.

The V2 contract uses null for all price, volume and value fields on a day
without trades. Missing rows/fields and inconsistent data remain blockers.
"""

from __future__ import annotations

import httpx
import pytest

from app.providers.jquants.mapping import map_daily_bar
from app.services.publication import classify_equity_input
from app.services.radar.features import MIN_BARS_FOR_FEATURES
from app.worker.tasks import _run_radar_and_screener
from tests.test_post_close_same_day_resync import (
    BAR_DATASETS,
    PREVIOUS,
    TARGET,
    _context,
    _Vendor,
    _wire_bar,
)
from tests.test_screener_freshness import _history, _seed
from tests.test_screener_schedule_e2e import _post_close_spec


WIRE_FIELDS = ("O", "H", "L", "C", "Vo", "Va", "AdjO", "AdjH", "AdjL", "AdjC", "AdjVo")
BAR_FIELDS = (
    "open", "high", "low", "close", "volume", "turnover_value",
    "adj_open", "adj_high", "adj_low", "adj_close", "adj_volume",
)
NO_TRADE_CODE = "228A0"


def _no_trade_wire(code=NO_TRADE_CODE):
    return {
        "Code": code, "Date": TARGET, "AdjFactor": 1.0, "UL": "0", "LL": "0",
        **{field: None for field in WIRE_FIELDS},
    }


def _classify(target_bar):
    return classify_equity_input(
        [*_history(NO_TRADE_CODE, PREVIOUS), target_bar],
        TARGET,
        min_feature_bars=MIN_BARS_FOR_FEATURES,
    )


def test_explicit_all_null_target_is_excluded_without_using_previous_price():
    mapped = map_daily_bar(_no_trade_wire())
    assert mapped is not None
    assert _classify(mapped) == ("excluded", None, "no_trades")
    # No previous price or long history is needed to recognize the explicit row.
    assert classify_equity_input([mapped], TARGET, min_feature_bars=MIN_BARS_FOR_FEATURES) == (
        "excluded", None, "no_trades"
    )


@pytest.mark.parametrize("field", BAR_FIELDS)
def test_missing_field_is_not_an_explicit_no_trade_row(field):
    mapped = map_daily_bar(_no_trade_wire())
    del mapped[field]
    bucket, _, reason = _classify(mapped)
    assert bucket == "invalid"
    assert reason != "no_trades"


@pytest.mark.parametrize("field", WIRE_FIELDS)
def test_mapper_does_not_turn_absent_vendor_field_into_explicit_null(field):
    wire = _no_trade_wire()
    del wire[field]
    assert map_daily_bar(wire) is None


@pytest.mark.parametrize("field,value", [
    ("Vo", "broken"), ("Va", float("nan")), ("C", float("inf")), ("AdjC", "invalid"),
])
def test_mapper_does_not_turn_invalid_numeric_value_into_no_trades(field, value):
    wire = _no_trade_wire()
    wire[field] = value
    assert map_daily_bar(wire) is None


def test_explicit_empty_csv_cells_keep_no_trade_semantics():
    wire = _no_trade_wire()
    wire.update({field: "" for field in WIRE_FIELDS})
    assert _classify(map_daily_bar(wire)) == ("excluded", None, "no_trades")


@pytest.mark.parametrize("field,value", [
    ("volume", 1.0), ("adj_volume", 1.0), ("turnover_value", 100.0),
    ("volume", 0.0), ("turnover_value", 0.0), ("open", 100.0),
    ("high", 101.0), ("low", 99.0), ("adj_open", 100.0),
    ("volume", float("nan")),
])
def test_non_null_price_or_activity_is_not_excluded(field, value):
    mapped = map_daily_bar(_no_trade_wire())
    mapped[field] = value
    assert _classify(mapped)[0] == "invalid"


def test_missing_close_with_other_quotes_or_missing_target_still_blocks():
    mapped = map_daily_bar(_wire_bar(NO_TRADE_CODE, C=None, AdjC=None))
    assert _classify(mapped)[0] == "invalid"
    missing = classify_equity_input(
        _history(NO_TRADE_CODE, PREVIOUS), TARGET, min_feature_bars=MIN_BARS_FOR_FEATURES
    )
    assert missing[0] == "unknown_missing" and missing[2] == "no_target_bar"


@pytest.mark.parametrize("history_length", [0, 4])
@pytest.mark.parametrize("updates", [
    {"C": None, "AdjC": None},
    {"C": -1, "AdjC": -1},
    {"C": "invalid", "AdjC": "invalid"},
    {"H": 99, "AdjH": 99, "L": 102, "AdjL": 102},
])
def test_short_history_does_not_hide_invalid_target_bar(history_length, updates):
    target = map_daily_bar(_wire_bar(NO_TRADE_CODE, **updates))
    rows = [*_history(NO_TRADE_CODE, PREVIOUS, n=history_length), target]
    bucket, _, reason = classify_equity_input(rows, TARGET, min_feature_bars=MIN_BARS_FOR_FEATURES)
    assert bucket == "invalid"
    assert reason not in {"no_trades", "insufficient_history"}


def test_valid_short_history_remains_excluded_and_bad_long_history_stays_invalid():
    target = map_daily_bar(_wire_bar(NO_TRADE_CODE))
    short = [*_history(NO_TRADE_CODE, PREVIOUS, n=4), target]
    assert classify_equity_input(short, TARGET, min_feature_bars=MIN_BARS_FOR_FEATURES) == (
        "excluded", None, "insufficient_history"
    )
    damaged = _history(NO_TRADE_CODE, PREVIOUS)
    for row in damaged:
        row.update(close=None, adj_close=None)
    bucket, _, _ = classify_equity_input(
        [*damaged, target], TARGET, min_feature_bars=MIN_BARS_FOR_FEATURES
    )
    assert bucket == "invalid"


class _RowsVendor(_Vendor):
    def __init__(self, rows):
        super().__init__()
        self.rows = rows

    def __call__(self, request):
        if request.url.path.endswith("/equities/bars/daily"):
            self.bar_requests.append(("/equities/bars/daily", request.url.params["date"]))
            return httpx.Response(200, json={"data": self.rows})
        return super().__call__(request)


def _worker_context(tmp_path, codes, rows):
    repo = _seed(tmp_path, codes, PREVIOUS)
    repo.upsert_trading_days([{"calendar_date": TARGET, "holiday_division": "1"}])
    vendor = _RowsVendor(rows)
    context, client = _context(repo, vendor)
    previous = _run_radar_and_screener(context, PREVIOUS)
    assert previous["outcome"] == "published"
    for dataset in BAR_DATASETS:
        repo.record_sync_success(dataset, checkpoint={"last_synced_date": PREVIOUS})
    return repo, vendor, context, client


def test_worker_excludes_no_trades_but_waits_for_unknown_member_then_publishes(tmp_path):
    codes = ["72030", NO_TRADE_CODE, "67580"]
    repo, vendor, context, client = _worker_context(
        tmp_path, codes, [_wire_bar("72030"), _no_trade_wire()]
    )
    try:
        previous_id = repo.strength_meta()["publication_id"]
        spec = _post_close_spec(context)
        incomplete = spec.run(None)
        coverage = incomplete.details["radar"]["coverage"]
        assert incomplete.outcome == "retained"
        assert (coverage["expected"], coverage["valid"], coverage["excluded"], coverage["unknown_missing"]) == (
            3, 1, 1, 1
        )
        assert coverage["reasons"]["no_trades"] == 1
        assert coverage["allows_complete_publish"] is False
        assert repo.strength_meta()["publication_id"] == previous_id

        vendor.rows.append(_wire_bar("67580"))
        complete = spec.run(None)
        assert complete.outcome == "published"
        coverage = repo.strength_meta()["coverage"]
        assert (coverage["valid"], coverage["excluded"], coverage["invalid"], coverage["unknown_missing"]) == (
            2, 1, 0, 0
        )
        assert coverage["allows_complete_publish"] is True
        assert coverage["reasons"]["no_trades"] == 1
        assert {row["canonical_code"] for row in repo.strength_rows_all()} == {"72030", "67580"}
        assert repo.strength_meta()["input_data_through"] == TARGET
        assert repo.screener_trade_date() == TARGET
        # The stored no-trade row remains null; no previous price was fabricated.
        stored = repo.bars_for_code(NO_TRADE_CODE, start_date=TARGET)[0]
        assert all(stored[field] is None for field in BAR_FIELDS)
        publication_id = repo.strength_meta()["publication_id"]
        assert spec.run(None).outcome == "already_current"
        assert repo.strength_meta()["publication_id"] == publication_id
    finally:
        client.close()


@pytest.mark.parametrize("malformed", ["missing_field", "invalid_value"])
def test_incomplete_vendor_row_cannot_be_normalized_into_no_trades(tmp_path, malformed):
    invalid_wire = _no_trade_wire()
    if malformed == "missing_field":
        del invalid_wire["Vo"]
    else:
        invalid_wire["Vo"] = "invalid"
    repo, _vendor, context, client = _worker_context(
        tmp_path, ["72030", NO_TRADE_CODE], [_wire_bar("72030"), invalid_wire]
    )
    try:
        previous_id = repo.strength_meta()["publication_id"]
        result = _post_close_spec(context).run(None)
        coverage = result.details["radar"]["coverage"]
        assert result.outcome == "retained"
        assert coverage["unknown_missing"] == 1 and coverage["excluded"] == 0
        assert coverage["allows_complete_publish"] is False
        assert repo.strength_meta()["publication_id"] == previous_id
        assert repo.bars_for_code(NO_TRADE_CODE, start_date=TARGET) == []
    finally:
        client.close()


def test_all_no_trade_rows_cannot_empty_or_advance_previous_publication(tmp_path):
    codes = ["72030", NO_TRADE_CODE]
    repo, _vendor, context, client = _worker_context(
        tmp_path, codes, [_no_trade_wire(code) for code in codes]
    )
    try:
        previous_meta = repo.strength_meta()
        previous_rows = repo.strength_rows_all()
        result = _post_close_spec(context).run(None)
        coverage = result.details["radar"]["coverage"]
        assert result.outcome == "retained"
        assert result.details["radar"]["reason"] == "empty_input"
        assert coverage["excluded"] == 2 and coverage["valid"] == 0
        assert repo.strength_meta() == previous_meta
        assert repo.strength_rows_all() == previous_rows
        assert repo.screener_trade_date() == PREVIOUS
        assert repo.sync_state("strength_snapshot")["data_through"] == PREVIOUS
    finally:
        client.close()
