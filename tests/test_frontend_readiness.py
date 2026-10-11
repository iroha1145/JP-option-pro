"""Readiness covers the deployed bundle and responds to asset replacement."""

import pytest


@pytest.fixture()
def runtime(tmp_path, monkeypatch):
    import app.main as main
    root = tmp_path / "frontend"
    assets = root / "assets"
    assets.mkdir(parents=True)
    (root / "index.html").write_text('<html><head><script src="/assets/main.js"></script><link rel="stylesheet" href="/assets/main.css"></head></html>')
    (assets / "main.js").write_text("import('./lazy.js')")
    (assets / "main.css").write_text("body{color:black}")
    (assets / "lazy.js").write_text("export default 1")
    monkeypatch.setattr(main, "FRONTEND_DIR", root)
    monkeypatch.setattr(main, "_INDEX_PATH", root / "index.html")
    monkeypatch.setattr(main, "_integrity_cache", None)
    return main, root


def test_readiness_covers_linked_assets_and_invalidates_cache(runtime):
    main, root = runtime
    first = main._frontend_integrity()
    assert first["ready"] and first["required_files"] == 4
    (root / "assets/main.js").unlink()
    assert main.ready().status_code == 503
    assert "assets/main.js" in main._frontend_integrity()["missing"]
    (root / "assets/main.js").write_text("replacement")
    assert main.ready().status_code == 200
    assert main._frontend_integrity()["sha256"] != first["sha256"]


def test_manifest_detects_missing_lazy_chunk(runtime):
    main, root = runtime
    (root / ".integrity-manifest").write_text("index.html\nassets/main.js\nassets/main.css\nassets/lazy.js\n")
    assert main._frontend_integrity()["ready"]
    (root / "assets/lazy.js").unlink()
    assert main.ready().status_code == 503
    assert "assets/lazy.js" in main._frontend_integrity()["missing"]


@pytest.mark.parametrize("manifest", ["../outside.js\n", "/outside.js\n", "", ".integrity-manifest\n"])
def test_invalid_manifest_fails_readiness(runtime, manifest):
    main, root = runtime
    (root / ".integrity-manifest").write_text(manifest)
    assert main.ready().status_code == 503


def test_invalid_html_encoding_fails_without_server_error(runtime):
    main, root = runtime
    (root / "index.html").write_bytes(b"\xff")
    assert main.ready().status_code == 503
    assert main._index_html_bytes() is None
