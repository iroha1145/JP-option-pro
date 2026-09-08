"""Real two-process deployment for browser tests; isolated disposable data."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import httpx
import pytest

ROOT=Path(__file__).resolve().parents[1]
EVIDENCE=Path(os.environ.get('JP_BROWSER_EVIDENCE',str(ROOT/'browser-evidence')))

@pytest.fixture()
def services(tmp_path,request):
    evidence=EVIDENCE/request.node.name.replace('/','_')
    evidence.mkdir(parents=True,exist_ok=True)
    data=tmp_path/'data'; data.mkdir()
    mode=tmp_path/'mode.txt'; mode.write_text('ok')
    config=tmp_path/'personal.toml'
    config.write_text('[access]\nmode="private_network"\nallowed_private_cidrs=["127.0.0.0/8","::1/128"]\n[features]\nintraday_quotes=false\nradar_enabled=true\nnews_mode="off"\n[radar]\nmin_avg_turnover_jpy=1000000.0\nmin_listed_days=60\n')
    with socket.socket() as s:
        s.bind(('127.0.0.1',0)); port=s.getsockname()[1]
    env={**os.environ,'DATA_DIR':str(data),'PERSONAL_CONFIG_PATH':str(config),
         'PYTHONPATH':str(ROOT/'backend'),'FRONTEND_DIR':str(ROOT/'frontend'),
         'HOST_BIND':'127.0.0.1','JP_TEST_PORT':str(port),'JP_TEST_MODE':str(mode)}
    for name in ('JQUANTS_API_KEY','OPENAI_API_KEY','APP_PASSWORD_HASH'): env.pop(name,None)
    seeded=subprocess.run([sys.executable,str(ROOT/'browser-tests/service.py'),'seed'],env=env,
                          cwd=ROOT,capture_output=True,text=True,check=True,timeout=30)
    before=json.loads(seeded.stdout)
    (evidence/'seed.json').write_text(json.dumps(before,ensure_ascii=False,indent=2))
    handles=[]; procs=[]
    base=f'http://127.0.0.1:{port}'
    try:
        for role in ('api','worker'):
            handle=(evidence/f'{role}.log').open('w'); handles.append(handle)
            procs.append(subprocess.Popen([sys.executable,str(ROOT/'browser-tests/service.py'),role],
                         cwd=ROOT,env=env,stdout=handle,stderr=subprocess.STDOUT))
        for _ in range(150):
            assert all(p.poll() is None for p in procs), 'fixture process exited; inspect service logs'
            try:
                if httpx.get(base+'/ready',timeout=.3).status_code==200: break
            except httpx.HTTPError: pass
            time.sleep(.1)
        else: raise AssertionError('API readiness timeout')
        yield {'base':base,'mode':mode,'evidence':evidence,'before':before,'data':data}
    finally:
        for proc in reversed(procs):
            proc.terminate()
            try: proc.wait(timeout=5)
            except subprocess.TimeoutExpired: proc.kill(); proc.wait(timeout=5)
        for handle in handles: handle.close()
