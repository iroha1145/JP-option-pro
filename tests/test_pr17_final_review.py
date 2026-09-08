"""Final-review regressions: exercise production scan, storage and sync paths."""
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import httpx
import pytest

from app.services.publication import expected_trade_date
from app.services.radar.engine import RadarEngine
from app.worker.tasks import _run_radar_and_screener, build_default_tasks, TASK_POST_CLOSE
from app.services import jquants_sync as sync
from app.providers.jquants.client import JQuantsClient
from tests.test_screener_freshness import _seed, _config, _bar
from tests.test_screener_schedule_e2e import _TaskCtx, _OkEngine

DAY = '2026-09-08'


def test_history_correction_changes_real_scan_fingerprint(tmp_path):
    repo = _seed(tmp_path, ['72030'], DAY)
    engine = RadarEngine(repo, _config())
    before = engine.scan(DAY, lookback_start='2026-01-01')
    bars = repo.bars_for_code('72030')
    corrected = dict(bars[-20])
    corrected['turnover_value'] = corrected['turnover_value'] * 4
    repo.upsert_daily_bars([corrected])
    after = engine.scan(DAY, lookback_start='2026-01-01')
    assert before['features_by_code']['72030']['avg_turnover_20d'] != after['features_by_code']['72030']['avg_turnover_20d']
    assert before['input_fingerprint'] != after['input_fingerprint']


def test_same_inputs_preserve_fingerprint(tmp_path):
    repo = _seed(tmp_path, ['72030'], DAY)
    engine = RadarEngine(repo, _config())
    assert engine.scan(DAY, lookback_start='2026-01-01')['input_fingerprint'] == engine.scan(DAY, lookback_start='2026-01-01')['input_fingerprint']


def test_same_day_failed_screener_repair_uses_publication_not_date(tmp_path, monkeypatch):
    repo = _seed(tmp_path, ['72030'], DAY)
    ctx = _TaskCtx(repo, _OkEngine(), target=DAY, radar=_config())
    first = _run_radar_and_screener(ctx, DAY)
    assert first['outcome'] == 'published'
    old_id = repo.strength_meta()['publication_id']
    old_turnover = repo.screener_query(where_sql='1', params=(), order_sql='canonical_code', limit=5, offset=0)[0][0]['turnover_value']
    repo.upsert_daily_bars([_bar('72030', DAY, 100, turnover_value=2e9)])
    original = repo.replace_screener_rows
    with monkeypatch.context() as patch:
        def fail_once(rows):
            raise RuntimeError('injected write failure')
        patch.setattr(repo, 'replace_screener_rows', fail_once)
        failed = _run_radar_and_screener(ctx, DAY)
        assert failed['status'] == 'error'
    repaired = _run_radar_and_screener(ctx, DAY)
    assert repaired['status'] == 'ok'
    new_id = repo.strength_meta()['publication_id']
    assert new_id != old_id
    actual = repo.screener_query(where_sql='1', params=(), order_sql='canonical_code', limit=5, offset=0)[0][0]
    assert actual['turnover_value'] != old_turnover
    assert actual['turnover_value'] == 2e9
    assert repo.sync_state('screener_snapshot')['checkpoint']['publication_id'] == new_id


def test_missing_current_calendar_row_is_unknown_even_one_day_gap(tmp_path):
    repo = _seed(tmp_path, ['72030'], '2026-09-07')
    assert repo.is_trading_day(DAY) is None
    expected = expected_trade_date(today=DAY, now=datetime(2026,9,8,18,tzinfo=ZoneInfo('Asia/Tokyo')), batch_hhmm='17:00', latest_trading_day=repo.latest_trading_day, session_status=repo.is_trading_day)
    assert expected is None


def test_explicit_holiday_preserves_previous_session(tmp_path):
    repo = _seed(tmp_path, ['72030'], '2026-09-07')
    repo.upsert_trading_days([{'calendar_date':DAY, 'holiday_division':'0'}])
    expected = expected_trade_date(today=DAY, now=datetime(2026,9,8,18,tzinfo=ZoneInfo('Asia/Tokyo')), batch_hhmm='17:00', latest_trading_day=repo.latest_trading_day, session_status=repo.is_trading_day)
    assert expected == '2026-09-07'


def test_missing_index_is_not_certified_as_fresh(tmp_path):
    repo = _seed(tmp_path, ['72030'], DAY)
    with repo.write() as connection:
        connection.execute('DELETE FROM index_bars')
    summary = RadarEngine(repo, _config()).scan(DAY, lookback_start='2026-01-01')
    assert summary['coverage']['index_input_date'] is None
    assert summary['coverage']['index_stale'] is True


class AuxSync(sync.JQuantsSyncEngine):
    def sync_margin_interest(self, target): return {'status': 'ok'}
    def sync_margin_alerts(self, target): return {'status': 'ok'}
    def sync_short_ratios(self, target): return {'status': 'ok'}
    def sync_short_positions(self, target): return {'status': 'ok'}
    def sync_earnings_calendar(self): return {'status': 'ok'}


def test_owner_batch_repulls_partially_checkpointed_target(tmp_path):
    repo = _seed(tmp_path, ['72030','67580'], '2026-09-07')
    repo.upsert_trading_days([{'calendar_date':DAY, 'holiday_division':'1'}])
    repo.upsert_daily_bars([_bar('72030', DAY, 100)])
    for dataset in (sync.DATASET_DAILY_PRICES, sync.DATASET_INDEX_PRICES):
        repo.record_sync_success(dataset, checkpoint={'last_synced_date': DAY}, data_through=DAY)
    requested=[]
    def vendor(request):
        requested.append(request.url.path)
        day = request.url.params['date']
        if request.url.path.endswith('/indices/bars/daily'):
            return httpx.Response(200,json={'data':[{'Date':day,'Code':'0000','C':2800}]})
        from tests.test_sync_publish_gap import _bar_row
        return httpx.Response(200,json={'data':[_bar_row(c,day) for c in ['72030','67580']]})
    client=JQuantsClient('test-only',transport=httpx.MockTransport(vendor),sleep=lambda _:None)
    ctx=_TaskCtx(repo, AuxSync(client,repo),target=DAY,radar=_config())
    task=next(t for t in build_default_tasks(ctx) if t.name==TASK_POST_CLOSE)
    result=task.run({'__action_type':'post_close_batch'})
    assert any(p.endswith('/equities/bars/daily') for p in requested), requested
    assert result.outcome=='published'
    assert repo.strength_meta()['trade_date']==DAY
    assert repo.strength_meta()['universe_count']==2


def test_unknown_calendar_task_has_explicit_non_success_outcome(tmp_path):
    repo=_seed(tmp_path,['72030'],'2026-09-07')
    ctx=_TaskCtx(repo,_OkEngine(),target=None,radar=_config())
    result=next(t for t in build_default_tasks(ctx) if t.name==TASK_POST_CLOSE).run(None)
    assert result.status=='skipped'
    assert result.outcome=='skipped'


def test_stale_retry_writer_cannot_clear_new_owner_state(tmp_path):
    from app.worker.state import WorkerStateRepository, WorkerLeaseLost
    from app.worker.runtime import WorkerSupervisor, TaskResult
    repo=WorkerStateRepository(tmp_path/'worker.db'); repo.initialize()
    supervisor=WorkerSupervisor(repo,[],owner_id='obsolete')
    supervisor._fencing_token=repo.acquire_lease('obsolete')
    repo.upsert_retry(task_name=TASK_POST_CLOSE,target_trade_date=DAY,dataset_scope='daily_bars',
                      reason='wait',next_retry_at='2099-09-08T17:20:00+09:00')
    # Controlled lease replacement, no changes to production lease durations.
    with repo.write() as c:
        c.execute("UPDATE worker_lease SET owner_id='replacement', fencing_token=fencing_token+1")
    task=TaskResult(status='completed',next_delay_seconds=86400,outcome='published',details={
        'retry':{'clear':True,'target_trade_date':DAY,'dataset_scope':'daily_bars'}})
    with pytest.raises(WorkerLeaseLost): supervisor._apply_retry_policy(TASK_POST_CLOSE,task,86400)
    assert repo.pending_retries_for_task(TASK_POST_CLOSE)


def test_retry_budget_does_not_fall_back_to_twenty_minute_loop(tmp_path):
    from app.worker.state import WorkerStateRepository
    from app.worker.runtime import WorkerSupervisor, TaskResult
    repo=WorkerStateRepository(tmp_path/'worker.db'); repo.initialize()
    supervisor=WorkerSupervisor(repo,[],owner_id='owner')
    supervisor._fencing_token=repo.acquire_lease('owner')
    repo.upsert_retry(task_name=TASK_POST_CLOSE,target_trade_date=DAY,dataset_scope='daily_bars',
                      reason='wait',next_retry_at='2020-01-01T00:00:00Z')
    with repo.write() as c: c.execute('UPDATE worker_retry_deadlines SET attempt_count=11')
    task=TaskResult(status='completed',next_delay_seconds=1200,outcome='waiting_input',details={
        'normal_next_delay_seconds':60000,'retry':{'target_trade_date':DAY,'dataset_scope':'daily_bars',
        'reason':'not_published','next_retry_at':'2099-01-01T00:00:00Z'}})
    assert supervisor._apply_retry_policy(TASK_POST_CLOSE,task,1200)==60000
    assert not repo.pending_retries_for_task(TASK_POST_CLOSE)


def test_stale_target_does_not_enter_radar_side_effects(tmp_path,monkeypatch):
    repo=_seed(tmp_path,['72030'],DAY)
    ctx=_TaskCtx(repo,_OkEngine(),target=DAY,radar=_config())
    assert _run_radar_and_screener(ctx,DAY)['outcome']=='published'
    def forbidden(*a,**kw): raise AssertionError('old target reached radar side effects')
    monkeypatch.setattr(RadarEngine,'scan',forbidden)
    out=_run_radar_and_screener(ctx,'2026-09-07')
    assert out['outcome']=='retained'
    assert out['reason']=='input_date_regression'


def test_filter_etag_binds_representation():
    from app.services.publication import strength_etag
    kwargs=dict(publication_id='p',stored_score_version='v',expected_trade_date_value=DAY,
                freshness={'freshness':'current'},universe_count=2)
    assert strength_etag(**kwargs,representation={'profile':'balanced'})!=strength_etag(**kwargs,representation={'profile':'aggressive'})


@pytest.mark.parametrize('corrupt',[
    {'input_data_through':'2099-01-01'},
    {'built_at':'not-a-timestamp'},
    {'built_at':'2099-01-01T00:00:00Z'},
])
def test_invalid_old_metadata_does_not_block_valid_recovery(tmp_path,corrupt):
    repo=_seed(tmp_path,['72030'],DAY)
    ctx=_TaskCtx(repo,_OkEngine(),target=DAY,radar=_config())
    first=_run_radar_and_screener(ctx,DAY)
    with repo.write() as c:
        for key,value in corrupt.items(): c.execute(f'UPDATE strength_meta SET {key}=? WHERE id=1',(value,))
    out=_run_radar_and_screener(ctx,DAY)
    assert out['outcome']=='published'
    assert repo.strength_meta()['publication_id']!=first['publication']['publication_id']
    assert repo.strength_meta()['input_data_through']==DAY


def test_screener_date_is_part_of_atomic_read_not_a_second_query(tmp_path,monkeypatch):
    from app.services.screener import run_screener,ScreenerFilters
    repo=_seed(tmp_path,['72030'],DAY)
    ctx=_TaskCtx(repo,_OkEngine(),target=DAY,radar=_config());_run_radar_and_screener(ctx,DAY)
    def forbidden(): raise AssertionError('date loaded outside row snapshot')
    monkeypatch.setattr(repo,'screener_trade_date',forbidden)
    result=run_screener(repo,ScreenerFilters())
    assert result['trade_date']==DAY
    assert result['rows'][0]['trade_date']==DAY
