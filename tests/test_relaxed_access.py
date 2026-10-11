"""Public read and account refresh permissions, without upstream requests."""
from types import SimpleNamespace

import pytest
from starlette.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    import app.main as main
    from app.api import account, screener, watchlist, worker_actions
    from app.access import current_request_can_refresh_public_data
    from app.access import OwnerAccessRuntime
    from app.personal_config import AccessConfig
    runtime = OwnerAccessRuntime(AccessConfig(mode="password"), password_hash="")
    monkeypatch.setattr(main.app.state, "access_runtime", runtime)
    monkeypatch.setattr(screener, "core_repository", lambda: SimpleNamespace(exists=lambda: True))
    monkeypatch.setattr(screener, "run_screener", lambda repo, filters: {"codes": filters.watchlist_codes, "can_refresh": current_request_can_refresh_public_data()})
    monkeypatch.setattr(watchlist, "current_account", lambda request: SimpleNamespace(user_id=request.headers['x-test-user']) if 'x-test-user' in request.headers else None)
    monkeypatch.setattr(account, "current_account", lambda request: SimpleNamespace(user_id="a") if "x-test-user" in request.headers else None)
    monkeypatch.setattr(worker_actions, "current_account", lambda request: SimpleNamespace(user_id='a') if 'x-test-user' in request.headers else None)
    monkeypatch.setattr(watchlist, "app_store", lambda: SimpleNamespace(account_watchlist=lambda uid: [{"canonical_code": uid}], watchlist=lambda: pytest.fail("owner data accessed")))
    monkeypatch.setattr(worker_actions, "worker_state_write", lambda: SimpleNamespace(exists=lambda: True, request_action=lambda *a, **kw: {"accepted": True, "action_id": 1}))
    main._rl_buckets.clear()
    with TestClient(main.app) as http:
        yield http


def test_public_screener_and_account_watchlist_isolation(client):
    assert client.post('/api/screener/query', json={}).status_code == 200
    body = {"watchlist_codes": ["__watchlist__"]}
    assert client.post('/api/screener/query', json=body).status_code == 401
    for user in ('72030', '67580'):
        response = client.post('/api/screener/query', json=body, headers={'x-test-user': user})
        assert response.status_code == 200
        assert response.json()['codes'] == [user]
        assert response.json()['can_refresh'] is True
    assert client.post('/api/screener/query', json={}).json()['can_refresh'] is False


def test_account_refresh_scope_and_same_origin(client):
    headers = {'x-test-user': 'a', 'Origin': 'http://testserver', 'X-Optix-Action': '1'}
    for action in ('radar_refresh', 'news_sync', 'short_monitor_refresh', 'intraday_fetch', 'tick_fetch'):
        assert client.post('/api/worker/actions/'+action, json={'code': '7203'}, headers=headers).status_code == 202
    for action in ('intraday_fetch', 'tick_fetch'):
        assert client.post('/api/worker/actions/'+action, json={'code':'7203'}).status_code == 401
        assert client.post('/api/worker/actions/'+action, json={'code':'7203'}, headers={**headers, 'Origin':'https://other.example'}).status_code == 403
    assert client.post('/api/worker/actions/post_close_batch', json={}, headers=headers).status_code == 401
    assert client.post('/api/worker/actions/radar_refresh', json={}).status_code == 401
    assert client.post('/api/worker/actions/radar_refresh', json={}, headers={**headers, 'Origin':'https://other.example'}).status_code == 403


def test_non_sensitive_unknown_config_and_dns_direct_tls(caplog):
    from app.personal_config import PersonalConfig
    from app.deployment_boundary import validate_deployment_boundary
    from pydantic import ValidationError
    config = PersonalConfig.model_validate({'sync': {'margin_weekly_time_jst':'17:40'}, 'features': {'retired_switch':True}})
    assert config.features.radar_enabled
    assert 'retired_switch' in caplog.text
    assert 'margin_weekly_time_jst' in caplog.text
    with pytest.raises(ValidationError):
        PersonalConfig.model_validate({'access': {'mode': 'public'}})
    result = validate_deployment_boundary('password', '127.0.0.1', 'jp.example.com', False, '', allowed_private_cidrs=())
    assert 'jp.example.com' in result.allowed_hosts
    with pytest.raises(RuntimeError):
        validate_deployment_boundary('password', '127.0.0.1', 'jp.example.com', True, '', allowed_private_cidrs=())


def test_task_status_reads_do_not_use_heavy_bucket(client, monkeypatch):
    import app.main as main
    calls = []
    monkeypatch.setattr(main, '_rate_limited', lambda key, *, heavy: calls.append(heavy) or False)
    client.get('/api/worker/actions/1')
    client.get('/api/market/overview')
    client.post('/api/screener/query', json={})
    assert calls == [False, False, True]


def test_compose_defaults_and_explicit_override(tmp_path):
    import os
    import subprocess
    from pathlib import Path
    docker = tmp_path / 'docker'
    docker.write_text('#!/bin/sh\nprintf "%s\\n" "$COMPOSE_PROJECT_NAME" "$@"\n')
    docker.chmod(0o755)
    env = {**os.environ, 'PATH': str(tmp_path)+os.pathsep+os.environ['PATH']}
    env.pop('COMPOSE_PROJECT_NAME', None)
    script = Path(__file__).resolve().parents[1] / 'scripts' / 'compose.sh'
    result = subprocess.run(['bash', str(script), '-f', 'custom.yml', '-p', 'jp-test', 'config', '-q'], env=env, capture_output=True, text=True, check=True)
    assert result.stdout.splitlines() == ['jp-option-pro', 'compose', '-f', 'custom.yml', '-p', 'jp-test', 'config', '-q']
