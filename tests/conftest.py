"""pytest 共通設定: backend を import path に載せ、環境を隔離する。"""

from __future__ import annotations

import os
import socket
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

# テストは実 J-Quants・実 OpenAI・実データディレクトリに触れない。
os.environ.setdefault("DATA_DIR", "/tmp/jp-test-conftest-unused")
os.environ.pop("JQUANTS_API_KEY", None)
os.environ.pop("OPENAI_API_KEY", None)


@pytest.fixture()
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    return tmp_path


# ---------------------------------------------------------------------------
# 外部ネットワーク遮断
# ---------------------------------------------------------------------------
#
# CI は実プロバイダ（J-Quants / Yahoo / 証券端末 / モデル API）に触らない、
# という取り決めを **仕組みで守らせる**。プロバイダ実装はどれも例外を握り
# 潰して「その銘柄は取れなかった」に変えるので、うっかり実接続しても
# テストは緑のまま通る —— 実際 1 本すり抜けていた（監視対象の差し替え先を
# 間違えたテストが Yahoo を叩いていた）。
#
# ループバックだけ許可し、それ以外は接続時点で落とす。実接続が要る手動の
# スモークテストは `@pytest.mark.allow_network` を付ける。

_REAL_SOCKET_CONNECT = socket.socket.connect
_LOOPBACK = {"127.0.0.1", "::1", "localhost", ""}


class ExternalNetworkBlocked(RuntimeError):
    pass


@pytest.fixture(autouse=True)
def _block_external_network(request, monkeypatch):
    if request.node.get_closest_marker("allow_network") is not None:
        yield
        return

    def guarded(self, address):
        host = address[0] if isinstance(address, tuple) else str(address)
        if host not in _LOOPBACK:
            raise ExternalNetworkBlocked(
                f"テストが外部へ接続しようとした: {host}\n"
                "夹具かモッククライアントを使ってください"
                "（実接続が要るなら @pytest.mark.allow_network）"
            )
        return _REAL_SOCKET_CONNECT(self, address)

    monkeypatch.setattr(socket.socket, "connect", guarded)
    yield


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "allow_network: 実プロバイダへの接続を許可する（手動スモーク用）"
    )
