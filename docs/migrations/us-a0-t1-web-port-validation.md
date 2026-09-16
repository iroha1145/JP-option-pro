# A0/T1 日本站迁移验证报告

对应提交（本文件落地时的工作树 HEAD；若随后只有文档微调，以该次测试运行的 commit 为准）：

| 项 | 值 |
|---|---|
| 验证 HEAD | `f8acfbc4dc0c766d098fc3151aecabcb2ecd4690` |
| TARGET_BASE_SHA | `a449ddb9ee89785eae22ea4c28174903c89d331c` |
| SOURCE_SHA | `98330ca4dc27af5e640484b3797ee7aa3d6f1573` |
| PR | https://github.com/iroha1145/JP-option-pro/pull/27 |
| 日期 | 2026-09-16 |

旧提交绿灯不能代替本 HEAD。下面每项都写了当时的证据。

## 结论

**不能称「全套通过」。** 在本环境对最终代码跑通了：全部现有 pytest（除 Playwright 当时未装 Chromium 的首次全集）+ 新增矩阵 + Playwright 生产前端 E2E + 隔离 uvicorn。完整 Docker 镜像构建为 **NOT RUN / BLOCKED**（本机无 `docker`）。未做生产库写入，未清空数据，未自动合并。

工程接通 ≠ 已证明日股收益率提高。本报告不包含收益率回测。

## 要求对照

| 要求 | 状态 | 证据 |
|---|---|---|
| 固定 TARGET_BASE_SHA / SOURCE_SHA | 满足 | `docs/migrations/us-a0-t1-web-port.md` |
| 美股 #167 最终语义（不完整输入不覆盖 settled；派发前预约次数） | 满足 | `t1_identity_complete` 不盲信 `identity_complete=True`；`complete_pending_t1` 先 `persist_required` 再 `fetcher`；`tests/test_t1_settled_and_identity.py`、`tests/test_t1_close_retry_budget.py` |
| 保留夜间全池 + 请求时轻量筛选 | 满足 | `/api/strength/scan` 对已保存断面 filter-then-sort；无 variant_demand |
| 保留 TOPIX / MA / 33 业种 / 日元 / canonical_code / J-Quants | 满足 | 未迁美国期权/纽约时区/SPY/QQQ；US residue gate 本地通过 |
| 原版默认，A0/T1 可选 | 满足 | `production` default；`follow_default`；profiles 广告 A0 `default: false` |
| A0 = 0.5 mid + 0.5 long；不填 None/NaN/Inf | 满足 | `tests/test_a0_ranking.py` |
| T1 只评估 `base_breakout` | 满足 | `tests/test_t1_priority_boost.py`、`tests/test_t1_daily_math.py` |
| RVOL ≠ turnover_ratio | 满足 | `tests/test_t1_volume_not_turnover.py` |
| 网页 API / 缓存身份 / 共享 / 乱序 / 偏好 / Owner 刷新 | 满足 | `queryRegistry` 参数化 identity；Screener owner refresh 轮询 action 后 `cache:'reload'`；普通 `runScan` 不 reload |
| 不改自动画线与标注定位 | 满足 | 未改 `chart-drawings`；现有 chart node gates 未删 |
| 真实生产入口测试 | 满足 | 算法模块 + CoreRepository/SQLite + WorkerSupervisor + FastAPI TestClient + 生产 `frontend/` Playwright |
| supervisor 外层取消（真实挂起，非抛 TimeoutError） | 满足 | `test_supervisor_wait_for_cancels_hanging_fetch_and_keeps_eight_budget`：`Event.wait()` + `wait_for`；日志 `/opt/cursor/artifacts/t1-hang-supervisor.log` |
| 现有测试 + 新矩阵 + CI | 部分 | 见下；完整镜像 **BLOCKED** |
| 交付 PR / 迁移说明 / 结果对应 HEAD | 满足 | PR #27；本文 + `us-a0-t1-web-port.md` |

## 本环境实测（最终代码）

命令：`PYTHONPATH=backend .venv/bin/python -m pytest tests/ -q --ignore=tests/test_a0_t1_browser.py`

结果：**742 passed, 1 skipped**（约 53s）。skip 是 `test_optional_production_image_build`（未设 `JP_REQUIRE_DOCKER_IMAGE=1`，且无 docker）。

随后：

- `tests/test_a0_t1_browser.py`：**2 passed**（320 日 fixture + 生产 `frontend/` + Chromium）
- `tests/test_a0_t1_container.py`：隔离 uvicorn **passed**；Dockerfile 静态检查 **passed**；镜像构建 **SKIPPED / BLOCKED**
- `frontend-src/tests/query-registry-identity.mjs` + `algorithm-preferences.mjs`：**11 passed**
- `dict_no_duplicates.mjs`：1390 keys, no duplicates
- US residue grep：无命中
- `diff -r frontend-src/dist frontend`：一致

### supervisor 八次预算

`test_supervisor_wait_for_cancels_hanging_fetch_and_keeps_eight_budget`：**passed**（约 1.3s）。挂起路径是 `await hang.wait()`，由 supervisor `asyncio.wait_for` 取消；`TimeoutError` 来自外层，不由任务主动抛出。兄弟事件 `evt-done` 保持 settled。

### Playwright

截图（本机 `/opt/cursor/artifacts/`）：

- `screener-a0-1440.png`：A0 中长期选中；状态 `a0_mid_long · jp-a0-mid-long-v1 · 0.5 * score_mid + 0.5 * score_long`；无「A0 分数不可计算」条
- `screener-a0-390.png`：手机宽度下算法段仍可见
- `radar-t1-390.png`：T1 日线优先选中

140 日 fixture 的 `score_long` 全空，A0 正确标 `a0_scores_unavailable`。E2E 改为 320 日以使长期族可算。这不是把失败藏起来，而是让浏览器门打到「A0 真能排序」而不是「分数缺失的诚实降级」（后者仍由 `test_a0_api.py` 覆盖）。

### 性能对比

`/opt/cursor/artifacts/a0-t1-perf.json`（进程内 TestClient + 17 只 fixture，**不是**生产硬件）：

| 视图 | 平均 ms | 冠军 | a0_status |
|---|---|---|---|
| production | 6.714 | 70130 | null |
| A0 | 6.646 | 70130 | active |

差值约 -0.07ms。该小宇宙上冠军碰巧相同；`tests/test_a0_api.py` 的发散池上冠军会从 72030 换成 99840。不能外推到全市场耗时或收益。

## 数据库

- `jp-core-v9` → `jp-core-v10`：`radar_t1_evaluations` / `radar_t1_current` / `radar_t1_retry`
- `jp-app-v2` → `jp-app-v3`：`view_preferences` / `algorithm_defaults`
- 回滚：还原代码到 `a449ddb` 并还原 schema 版本/备份库。禁止删生产 `jp-core.db`。详见 `us-a0-t1-web-port.md`

`tests/test_a0_t1_migration.py`：v9→v10 保行且幂等；v2→v3 加偏好表。

## 未运行 / 受阻

| 项 | 标记 | 原因 |
|---|---|---|
| 完整 production 镜像 `docker build` | **NOT RUN / BLOCKED** | 本环境无 `docker`；CI 中需 `JP_REQUIRE_DOCKER_IMAGE=1` |
| 生产 jp-core.db 实库迁移演练 | **NOT RUN** | 任务禁止清空/改生产数据 |
| 日股收益率 / 回测 | **NOT RUN** | 不在工程验收范围，禁止写成已证明 |
| GitHub Actions 在本 PR 上的远端 CI | 以 GitHub 当时运行为准 | 本地已按同一套命令跑 |

## CI 接入

`.github/workflows/ci.yml`：

- 后端全集忽略 Playwright（先装 Chromium 再跑浏览器门）
- query-registry / algorithm-preferences node 门
- 隔离 uvicorn + hang 预算复跑
- Playwright Chromium 安装与 `tests/test_a0_t1_browser.py`
