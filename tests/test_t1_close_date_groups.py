"""F5: complete_pending_t1 groups by trade date and persists local conclusions first."""

from __future__ import annotations

import asyncio
from datetime import timedelta

from app.services.radar.t1_close import complete_pending_t1
from app.services.radar.t1_priority import T1_MET, T1_UNMET
from tests.support.a0_t1_fixtures import (
    SESSION,
    SESSION_ISO,
    history_plus_session,
    init_repo,
    insert_radar_event,
    insert_security,
    jst,
    prior_weekdays,
    t1_bar,
)

OLD = SESSION
NEW = SESSION + timedelta(days=1)
OLD_ISO = OLD.isoformat()
NEW_ISO = NEW.isoformat()


def _seed_two_dates(tmp_path, *, old_has_t=False, new_has_t=False, sibling_local=True):
    repo = init_repo(tmp_path / "jp-core.db")
    insert_security(repo, "72030")
    insert_security(repo, "67580")
    insert_security(repo, "99840")
    old_priors = [t1_bar("72030", day) for day in prior_weekdays(OLD, 20)]
    new_priors = [t1_bar("67580", day) for day in prior_weekdays(NEW, 20)]
    if old_has_t:
        old_priors = history_plus_session("72030", OLD)
    if new_has_t:
        new_priors = history_plus_session("67580", NEW)
    repo.upsert_daily_bars(old_priors + new_priors)
    insert_radar_event(repo, event_id="evt-old", code="72030", discovered=OLD_ISO, last_scanned=NEW_ISO)
    insert_radar_event(repo, event_id="evt-new", code="67580", discovered=NEW_ISO, last_scanned=NEW_ISO)
    if sibling_local:
        repo.upsert_daily_bars(history_plus_session("99840", NEW))
        insert_radar_event(repo, event_id="evt-local", code="99840", discovered=NEW_ISO, last_scanned=NEW_ISO)
    return repo


def test_mixed_dates_fetch_each_trade_date_and_do_not_exhaust_old(tmp_path):
    repo = _seed_two_dates(tmp_path, old_has_t=False, new_has_t=False, sibling_local=False)
    calls: list[tuple[list[str], str]] = []

    async def fetch(codes, day):
        calls.append((list(codes), day))
        if day == OLD_ISO:
            return {"72030": history_plus_session("72030", OLD)}
        return {}

    result = asyncio.run(
        complete_pending_t1(repo, as_of=jst(18, 0, NEW), fetcher=fetch, retry_base_seconds=0.01)
    )
    assert {day for _codes, day in calls} == {OLD_ISO, NEW_ISO}
    old_key = f"evt-old|{OLD_ISO}|t1_daily_priority"
    new_key = f"evt-new|{NEW_ISO}|t1_daily_priority"
    states = repo.load_t1_retry_states([old_key, new_key])
    assert old_key not in states or states[old_key]["exhausted"] is False
    assert states[new_key]["attempt"] == 1
    overlay = {item["event_id"]: item for item in repo.overlay_t1_evaluations(repo.applicable_t1_events())}
    assert overlay["evt-old"]["t1_priority"]["status"] in {T1_MET, T1_UNMET}
    assert result["completed"] >= 1


def test_local_ready_persists_before_remote_group_fails(tmp_path):
    repo = _seed_two_dates(tmp_path, old_has_t=False, new_has_t=False, sibling_local=True)
    hang = asyncio.Event()

    async def hanging_fetch(codes, day):
        if day == OLD_ISO:
            await hang.wait()
        return {}

    async def run():
        task = asyncio.create_task(
            complete_pending_t1(
                repo, as_of=jst(18, 0, NEW), fetcher=hanging_fetch, retry_base_seconds=0.01,
            )
        )
        await asyncio.sleep(0.05)
        local = repo.overlay_t1_evaluations([{"event_id": "evt-local"}])[0].get("t1_priority") or {}
        assert local.get("status") in {T1_MET, T1_UNMET}
        hang.set()
        return await task

    result = asyncio.run(run())
    assert result["completed"] >= 1
    kept = repo.overlay_t1_evaluations([{"event_id": "evt-local"}])[0]["t1_priority"]
    assert kept["status"] in {T1_MET, T1_UNMET}


def test_remote_exception_does_not_drop_already_persisted_local(tmp_path):
    repo = _seed_two_dates(tmp_path, old_has_t=False, new_has_t=False, sibling_local=True)

    async def boom(_codes, _day):
        raise RuntimeError("vendor down")

    result = asyncio.run(
        complete_pending_t1(repo, as_of=jst(18, 0, NEW), fetcher=boom, retry_base_seconds=0.01)
    )
    assert result["completed"] >= 1
    kept = repo.overlay_t1_evaluations([{"event_id": "evt-local"}])[0]["t1_priority"]
    assert kept["status"] in {T1_MET, T1_UNMET}
    assert result["reason"] in {None, "daily_fetch_failed"}
