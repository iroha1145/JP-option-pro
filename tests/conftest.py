"""pytest 共通設定: backend を import path に載せ、環境を隔離する。"""

from __future__ import annotations

import os
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
