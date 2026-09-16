# A0/T1 日本站迁移验证报告

对应提交（本文件落地时的工作树可能随后只有文档微调；**实测与 CI 以该次代码 commit 为准**）：

| 项 | 值 |
|---|---|
| 验证 HEAD（代码 + CI） | `ca50ab7f4599628e341f10946c590b15b55c73df` |
| 本地全集 pytest HEAD | `d3050ec43d5f63ba793d6e1ba1b9e97c543b1637`（`ca50ab7` 相对它只去掉 leftover `or True` 并记录 CI） |
| TARGET_BASE_SHA | `a449ddb9ee89785eae22ea4c28174903c89d331c` |
| SOURCE_SHA | `98330ca4dc27af5e640484b3797ee7aa3d6f1573` |
| PR | https://github.com/iroha1145/JP-option-pro/pull/27 |
| 日期 | 2026-09-16 |

旧提交绿灯（含审查基线 `195a743` / 修复提交 `8674a15` / 文档钉 `b5a8528`）不能代替本 HEAD。下面每项都写了当时的证据。

## 结论

本地对 `d3050ec` 跑通全部 pytest + 新增矩阵 + Playwright + WAL。本机无 `docker`，镜像步本地 **NOT RUN**。远端 CI 在 **`ca50ab7` 终态 success**：

- push `35073693026`（2026-09-16T08:27:50Z）
- PR `35073696875`（2026-09-16T08:27:59Z）

镜像硬门真实 `docker build` + 容器 `/ready` `/health` A0 scan，Playwright **2 passed**。未做生产库写入，未清空数据，未自动合并，未标 ready。

工程接通 ≠ 已证明日股收益率提高。本报告不包含收益率回测。

## 审查反例 → 修复后

| 缺陷 | 旧反例 | 修复后 |
|---|---|---|
| F1 冻结锚 | T1 读当日 `features.structure.base.resistance_high`；引擎每日覆盖。`pivot_price` 是 mid，不能盲恢复。 | `radar_t1_anchors`（`jp-core-v11`）首次发布写入 `INSERT OR IGNORE`。`t1_resistance_high` 只读专用锚或书面 `t1_anchor_recovery`。T+1 新平台不改 T 日锚 / `first_known_at`。 |
| F2 ETag | 只吃日期/条数时，priority/T1/short 变了仍 304。 | `_radar_content_etag` 哈希已组装页 + 全部 filter（含 `short_*`）+ 事件状态/价格/T1/short。同数据同请求 304，内容变则 200。不另拉一遍行情只为比 ETag。 |
| F3 T1 提升 | 先截 400 再 boost；零 met 也重排。 | 无限候选 → overlay → `apply_t1_stable_boost` → 再分页。零可提升事件原序逐项保留。组内稳定分区写回原槽位。`matched_count` 是真实总数。 |
| F4 偏好 | 身份/世代/AbortSignal 未接入真链；匿名 GET `follow_default` 占位、雷达只 PUT T1 会把选股写成 `follow_default`。 | `bindPreferenceWritePrincipal` / 世代 / `{ signal }`。未登录不套用 GET 占位。部分 PUT 合并另一族。Owner 环回 PUT T1 后重挂载仍保持 A0。 |
| F5 收盘补评 | 混用 `session_dates[0]`；先等远程再落库。 | 按交易日分组 fetch、只扣该日预算、本地结论先 persist。外层取消仍是真实挂起 `Event.wait()`。 |

未加入 C0/C1/T2/F1/F2 权重。

## 要求对照

| 要求 | 状态 | 证据 |
|---|---|---|
| 固定 TARGET_BASE_SHA / SOURCE_SHA | 满足 | `docs/migrations/us-a0-t1-web-port.md` |
| 美股 #167 最终语义（不完整输入不覆盖 settled；派发前预约次数） | 满足 | `t1_identity_complete` 不盲信 `identity_complete=True`；`complete_pending_t1` 先 persist 再 fetch；`tests/test_t1_settled_and_identity.py`、`tests/test_t1_close_retry_budget.py` |
| 保留夜间全池 + 请求时轻量筛选 | 满足 | `/api/strength/scan` 对已保存断面 filter-then-sort；无 variant_demand |
| 保留 TOPIX / MA / 33 业种 / 日元 / canonical_code / J-Quants | 满足 | 未迁美国期权/纽约时区/SPY/QQQ；US residue gate CI 通过 |
| 原版默认，A0/T1 可选 | 满足 | `production` default；`follow_default`；profiles 广告 A0 `default: false` |
| A0 = 0.5 mid + 0.5 long；不填 None/NaN/Inf | 满足 | `tests/test_a0_ranking.py`（含在 766/768 全集） |
| T1 只评估 `base_breakout` | 满足 | `tests/test_t1_priority_boost.py`、`tests/test_t1_daily_math.py` |
| T1 阻力冻结 | 满足 | `tests/test_t1_frozen_anchor.py` |
| RVOL ≠ turnover_ratio | 满足 | `tests/test_t1_volume_not_turnover.py` |
| 网页 API / 缓存身份 / 共享 / 乱序 / 偏好 / Owner 刷新 | 满足 | 参数化 queryRegistry；Screener/Radar PUT 带 signal 且写两族；部分 UPSERT 合并；Owner refresh 绑定 action + publication |
| 不改自动画线与标注定位 | 满足 | 未改 `chart-drawings`；现有 chart node gates 未删 |
| 真实生产入口测试 | 满足 | 算法 → CoreRepository/SQLite → WorkerSupervisor → FastAPI → 生产 `frontend/` Playwright |
| supervisor 外层取消（真实挂起，非抛 TimeoutError） | 满足 | `test_supervisor_wait_for_cancels_hanging_fetch_and_keeps_eight_budget`：`Event.wait()` + `wait_for` |
| 现有测试 + 新矩阵 + CI | 满足 | 本地 `d3050ec`：768 passed。CI `ca50ab7` push `35073693026` / PR `35073696875`：success。后端 766 passed；隔离 12 passed；Docker 镜像步 success；Playwright 2 passed |
| 交付 PR / 迁移说明 / 结果对应 HEAD | 满足 | PR #27 draft；分支已推。本环境 `ManagePullRequest` 因仓库改名无法改 PR 正文。验收以本文 + CI run 为准。 |

## 本环境实测（代码 `d3050ec`；CI 复跑 `ca50ab7`）

命令：`PYTHONPATH=backend .venv/bin/python -m pytest tests/ -q --tb=no`

结果：**768 passed, 0 skipped**（402.56s）。原始输出：`/opt/cursor/artifacts/pytest-full-d3050ec.log`。

此前不含浏览器的全集：`tests/ -q --ignore=tests/test_a0_t1_browser.py` → **766 passed**（62.20s）。

随后单独复跑：

- `tests/test_a0_t1_browser.py`：**2 passed**
- `tests/test_a0_t1_container.py`：隔离 uvicorn + WAL backend/worker **passed**；本机无 docker，不跑镜像
- `tests/test_t1_frozen_anchor.py` / `test_radar_t1_view_identity.py` / `test_t1_close_date_groups.py` / `test_view_preferences.py`：**passed**（含部分 PUT 合并）
- 前端 identity / 偏好 / session：**17 passed**
- `dict_no_duplicates.mjs`：1390 keys, no duplicates
- US residue grep：无命中
- `diff -r frontend-src/dist frontend`：一致
- `ca50ab7` 去掉 `tests/test_t1_calendar_publication.py` leftover `or True`；CI 在该尖复跑上述门

### supervisor 八次预算

`test_supervisor_wait_for_cancels_hanging_fetch_and_keeps_eight_budget`：**passed**。挂起路径是 `await hang.wait()`，由 supervisor `asyncio.wait_for` 取消；`TimeoutError` 来自外层，不由任务主动抛出。兄弟事件保持 settled。

### Playwright

夹具把生产冠军与 A0/T1 冠军拆开（strength 改分；雷达用 `evt-prod-lead` / `evt-t1-lead` + 已落库 T1 met）。日语 locale。

断言：

1. 首行 `canonical_code` 从生产冠军变为 A0 冠军（桌面 `.first` + 手机 `.nth(1)`）。
2. 雷达首事件从生产 lead 变为 T1 lead。
3. 进雷达再回选股：本地 A0 仍在，首行仍是 A0 冠军（修复：重挂载先扫本地；未登录不套用 GET 占位；部分 PUT 合并另一族）。
4. PUT 503 后出现未同步徽标，排序仍切到原版。

截图（`/opt/cursor/artifacts/`）：

- `manual_screener_production_first_row.webp` / `manual_screener_a0_first_row.webp`
- `manual_screener_a0_after_radar_remount.webp` / `manual_radar_t1_lead.webp`
- `screener-a0-1440.png` / `screener_a0_desktop_first_row.png`
- `screener-a0-390.png` / `screener_a0_mobile_algorithm.png`
- `radar-t1-390.png` / `radar_t1_mobile_lead.png`

无头 Chromium 在缺日文字体时截图可能出现方框，DOM 断言仍按 `data-canonical-code` / `data-event-id` / 算法状态文本通过。已污染或 0 字节的录屏不作验收。

### 性能（代表池，不是 17 名 6ms）

`/opt/cursor/artifacts/a0-t1-representative-perf.json`（TestClient，400 只强度 / 80 条雷达）：

| 视图 | ms | 冠军 |
|---|---|---|
| strength production cold | 37.751 | 72030 |
| strength A0 cold | 23.72 | 99840 |
| strength A0 hot | 21.5 | 99840 |
| radar production | 46.954 | — |
| radar T1 | 40.296 | — |

冠军不同。不能外推到全市场耗时或收益。旧的 17 名 `/opt/cursor/artifacts/a0-t1-perf.json` 只作对照，不作验收。

## 数据库

- `jp-core-v9` → `jp-core-v10`：`radar_t1_evaluations` / `radar_t1_current` / `radar_t1_retry`
- `jp-core-v10` → `jp-core-v11`：`radar_t1_anchors`（checksum `8ecadfcb4b565d407d2dc28726e430ceb5b9bcf46057d799bf285ad2ec80e4fd`）
- `jp-app-v2` → `jp-app-v3`：`view_preferences` / `algorithm_defaults`
- 回滚：还原代码到 `a449ddb` 并还原 schema 版本/备份库。禁止删生产 `jp-core.db`。详见 `us-a0-t1-web-port.md`

已经保存的不可靠 T1：无冻结锚、也没有「当时 pivot 就是阻力高且口径一致」书面记录的，重评为 `not_applicable`。不要用生产 `pivot_price` 盲恢复。

## 未运行 / 受阻

| 项 | 标记 | 原因 |
|---|---|---|
| 完整 production 镜像（本机） | **NOT RUN / BLOCKED** | 本环境无 `docker` |
| 完整 production 镜像（CI） | **passed** | `ca50ab7` push `35073693026` 步 `Production Docker image + isolated API`：`docker build -f backend/Dockerfile -t jp-option-pro-a0-t1:ci`，`naming to docker.io/library/jp-option-pro-a0-t1:ci done`，`docker run` 名为 `jp-a0-t1-api`，断言 A0 `effective_algorithm`。无 skip |
| 生产 jp-core.db 实库迁移演练 | **NOT RUN** | 任务禁止清空/改生产数据 |
| 日股收益率 / 回测 | **NOT RUN** | 不在工程验收范围 |
| 用 ManagePullRequest 更新 PR 正文 | **BLOCKED** | origin 仍是 `iroha1145/jp-option-pro`，源已迁到 `iroha1145/JP-option-pro`。未改用 `gh` 写操作 |
| GitHub Actions | **success** | push `35073693026`、PR `35073696875`，HEAD `ca50ab7`，2026-09-16T08:27Z 终态 |

## CI 接入

`.github/workflows/ci.yml`：

- 后端全集忽略 Playwright（先装 Chromium 再跑浏览器门）
- query-registry / algorithm-preferences / preference-session node 门
- 隔离 uvicorn + hang 预算 + 按日 fetch + WAL
- `docker build` + 容器内 `/ready` `/health` `/api/strength/scan?ranking_algorithm=a0`（无 skip-as-pass）
- Playwright Chromium 安装与 `tests/test_a0_t1_browser.py`

`ca50ab7` 实测（push `35073693026`）：Backend tests **766 passed / 53.40s**；Isolated A0/T1 **12 passed / 4.17s**；Docker 镜像步 **success**（build+run+A0 curl）；Playwright **2 passed / 6.93s**。PR run `35073696875`：766 / 12 / Docker success / Playwright **2 passed / 7.09s**。日志摘录：`/opt/cursor/artifacts/ci-ca50ab7-evidence.txt`。
