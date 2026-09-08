"""Isolated browser-test services; no test hooks are installed in the app.

Only external vendor I/O, unrelated auxiliary feeds and the market clock are
substituted. Daily/index mapping, sync checkpoints, computation, auth, API,
queue, supervisor, file lock and database publications are production code.
"""
import asyncio
from datetime import date, datetime
import json
import os
from pathlib import Path
import signal
import socket
import sys
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
import app.domain.timeutil as clock
clock.now_jst = lambda: datetime(2026, 9, 8, 18, 0, tzinfo=ZoneInfo('Asia/Tokyo'))
clock.today_jst = lambda: date(2026, 9, 8)

original_connect = socket.socket.connect
def isolated_connect(self, address):
    if isinstance(address, tuple) and address[0] not in {'127.0.0.1', '::1', 'localhost'}:
        raise RuntimeError('external test connection blocked')
    return original_connect(self, address)
socket.socket.connect = isolated_connect

from app.data_paths import get_data_paths
from app.repositories.core import CoreRepository
from app.services import jquants_sync as sync

if sys.argv[1] == 'seed':
    from app.tools.dev_fixture import build_fixture
    result = build_fixture(os.environ['DATA_DIR'], days=140, end_date=date(2026,9,7))
    repo = CoreRepository(get_data_paths().core_db)
    for dataset in (sync.DATASET_DAILY_PRICES, sync.DATASET_INDEX_PRICES):
        repo.record_sync_success(dataset, checkpoint={'last_synced_date':'2026-09-07'}, data_through='2026-09-07')
    print(json.dumps(result, default=str))
elif sys.argv[1] == 'api':
    import uvicorn
    uvicorn.run('app.main:app', host='127.0.0.1', port=int(os.environ['JP_TEST_PORT']), log_level='warning')
elif sys.argv[1] == 'worker':
    import httpx
    from app.providers.jquants.client import JQuantsClient
    from app.worker.tasks import TaskContext, build_default_tasks, TASK_POST_CLOSE
    from app.worker.runtime import WorkerSupervisor, TaskSpec
    from app.worker.state import WorkerStateRepository
    from app.worker.lock import ProcessFileLock

    class VendorEngine(sync.JQuantsSyncEngine):
        def sync_margin_interest(self, target): return {'status':'ok'}
        def sync_margin_alerts(self, target): return {'status':'ok'}
        def sync_short_ratios(self, target): return {'status':'ok'}
        def sync_short_positions(self, target): return {'status':'ok'}
        def sync_earnings_calendar(self): return {'status':'ok'}

    class Context(TaskContext):
        def __init__(self):
            super().__init__()
            # Preserve the fixture's genuine previous-session prices. New raw
            # vendor rows are mapped by the production J-Quants sync engine.
            self.old = {s['canonical_code']: self.repository.bars_for_code(s['canonical_code'])[-1]
                        for s in self.repository.list_securities(active_only=True)}
            self._client = JQuantsClient('fixture-only', transport=httpx.MockTransport(self.vendor),
                                         sleep=lambda _: None, max_attempts=1)
        def jquants_ready(self): return True
        @property
        def engine(self): return VendorEngine(self.client, self.repository)
        def vendor(self, request):
            mode = Path(os.environ['JP_TEST_MODE']).read_text().strip()
            day = request.url.params.get('date')
            print(json.dumps({'vendor_path':request.url.path,'date':day,'mode':mode}), flush=True)
            if request.url.path.endswith('/equities/bars/daily'):
                if mode == 'fail': return httpx.Response(503, json={'message':'synthetic unavailable'})
                if mode == 'wait': return httpx.Response(200, json={'data':[]})
                rows=[]
                for code, bar in self.old.items():
                    close=float(bar['adj_close'] or bar['close'])*1.03
                    vol=2_000_000.0
                    rows.append({'Date':day,'Code':code,'O':close*.99,'H':close*1.02,
                                 'L':close*.98,'C':close,'Vo':vol,'Va':vol*close,
                                 'AdjO':close*.99,'AdjH':close*1.02,'AdjL':close*.98,
                                 'AdjC':close,'AdjVo':vol,'AdjFactor':1})
                return httpx.Response(200,json={'data':rows})
            if request.url.path.endswith('/indices/bars/daily'):
                return httpx.Response(200,json={'data':[{'Date':day,'Code':'0000','O':2800,'H':2840,'L':2780,'C':2820}]})
            raise AssertionError(f'unexpected vendor endpoint {request.url.path}')

    async def run():
        paths=get_data_paths(); owner=f'browser-fixture-{os.getpid()}'
        lock=ProcessFileLock(paths.worker_lock)
        if not lock.acquire(owner): raise RuntimeError('fixture lock unavailable')
        try:
            state=WorkerStateRepository(paths.worker_db); state.initialize()
            context=Context()
            real=next(t for t in build_default_tasks(context) if t.name==TASK_POST_CLOSE)
            task=TaskSpec(name=real.name,run=real.run,initial_delay_seconds=3600,
                          action_types=real.action_types,failure_backoff_seconds=real.failure_backoff_seconds,
                          max_backoff_seconds=real.max_backoff_seconds)
            supervisor=WorkerSupervisor(state,[task],owner_id=owner,action_poll_seconds=.1)
            loop=asyncio.get_running_loop()
            for sig in (signal.SIGTERM,signal.SIGINT): loop.add_signal_handler(sig,supervisor.request_stop)
            await supervisor.run()
        finally:
            lock.release()
    asyncio.run(run())
else:
    raise SystemExit('seed, api or worker required')
