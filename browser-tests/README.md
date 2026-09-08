# PR17 browser verification

Run after producing `frontend/` with the repository's production build:

```sh
python -m pip install -r browser-tests/requirements.txt
python -m playwright install --with-deps chromium
PYTHONPATH=backend python -m pytest browser-tests/ -q
```

All data is synthetic. Each case owns a disposable database directory, two
independent API/worker processes and one Chromium context. `service.py` freezes
the market observation clock at 2026-09-08 18:00 JST, uses the existing real
private-network owner authentication on loopback, and blocks external sockets.
Only vendor transport and unrelated auxiliary feed methods are substituted.
Daily/index rows still pass through production mapping, synchronization,
cleaning, scoring, durable queue, supervisor and publication code.

`test_owner_pipeline_changes_real_publication` (desktop/mobile) and
`test_provider_failure_then_recovery` (HTTP failure/empty publication) traverse
that complete path. Focused race and invalid receipt cases intercept specified
HTTP responses to control timing; they are UI tests, not additional provider
integration tests. Route checks cover three interface languages and two sizes;
these are simulated Chromium viewports, not physical devices.

Artifacts are written to `JP_BROWSER_EVIDENCE` (default `browser-evidence/`):
traces, screenshots, response path/status summaries, synthetic publication
receipts and service logs. No cookies or environment dumps are logged. The
Playwright trace is useful execution evidence, but is not an assertion report;
pytest/JUnit remains authoritative for pass/fail. Each browser case must also
finish without JavaScript page errors or attempted external connections.

`container-smoke.sh` separately builds the production image and starts API/worker
containers with disposable storage, `--network none`, a read-only root and no
credentials. This is a container boot/WAL/permission test, not an external-vendor
integration test. It deletes only its uniquely named resources.
