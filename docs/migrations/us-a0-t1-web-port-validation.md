# A0/T1 日本站迁移验证报告

对应提交（本文件落地时的工作树可能随后只有文档微调；**实测与 CI 以该次代码 commit 为准**）：

| 项 | 值 |
|---|---|
| 验证 HEAD（本轮三项 P2 代码） | `d83aa3226bd3ac5fdfc13a4c9c7d768ce0aedd10` |
| 本地全集 pytest | `d83aa32`：**779 passed**（776 非浏览器 + 3 Playwright，133.82s） |
| 本轮代码 CI | `d83aa32` 终态 **success**：push `35076660156` / PR `35076663889` |
| 上一轮代码 + CI | `ca50ab7f4599628e341f10946c590b15b55c73df` |
| TARGET_BASE_SHA | `a449ddb9ee89785eae22ea4c28174903c89d331c` |
| SOURCE_SHA | `98330ca4dc27af5e640484b3797ee7aa3d6f1573` |
| PR | https://github.com/iroha1145/JP-option-pro/pull/27 |
| 日期 | 2026-09-16 |

## 本轮三项 P2（复核 `2a741a04`）

本地对 `d83aa32` 跑通全部 pytest。本机无 `docker`，镜像步本地 **NOT RUN**。远端 CI 在 **`d83aa32` 终态 success**：

- push `35076660156`（2026-09-16T08:57:29Z → 09:00:58Z）
- PR `35076663889`（2026-09-16T08:57:31Z → 09:01:02Z）

CI 计数：后端 **776 passed**（55.86s）；隔离 **12 passed**；Docker 镜像硬门 `docker build` + `/ready` `/health` A0 scan **success**；Playwright **3 passed**（72.60s）；dict 1390 / byte gate / US residue 均 success。

| 项 | 修复前 | 修复后（真实算法 → SQLite → API / 生产前端） |
|---|---|---|
| T1 计价基准 | 冻结锚 100，日后 `adj_*` 半价，distance 2.58→−41.87，met→unmet | T 窗优先 raw×截止 T 因子重建到事件日基准；有书面拆股因子才换算 `adj_*`。纯等比例 restatement 后仍 met、distance/CLV/RVOL 不变、`first_known_at` 不变。无可靠比例时保留 settled + `latest_attempt.reason=price_basis_unreliable` |
| ETag | `base_quality` 80→30 或 `support_low` 95→91，带旧 ETag 仍 304 | `_canonical_event_view` 哈希完整事件正文。production/T1 嵌套分/结构/snapshot 变则 200；同内容 304；short 过滤身份不合并 |
| 偏好 GET | Alice GET 迟到可把 Bob 可见算法改成 T1 | `preferenceIdentityEpoch` + effect cleanup/AbortSignal。Playwright：Alice GET 挂起 → Bob production → 释放 Alice T1，雷达/选股仍是 Bob production；登出后迟到 GET 不能写成 A0 |

未加入新策略权重。原版默认、A0=0.5 mid+0.5 long、T1 四条件、全池雷达排序、按日取数、本地先落库、写队列隔离均保留。

本轮新增/改写的真实回归：`tests/test_t1_price_basis.py`、`test_split_adjust_revises_identity_but_keeps_anchor`、`test_radar_t1_view_identity.py` 嵌套 ETag、`test_playwright_stale_preference_get_cannot_override_new_identity`、前端 epoch 门。

旧提交绿灯（含审查基线 `195a743` / 修复提交 `8674a15` / 文档钉 `b5a8528`）不能代替本 HEAD。下面每项都写了当时的证据。

## 结论

本轮三项 P2 以 `d83aa32` 为准：本地 **779 passed**；CI push `35076660156` / PR `35076663889` **success**（后端 776、隔离 12、Docker 硬门、Playwright 3）。本机无 `docker`，镜像步本地 **NOT RUN**。上一轮 F1–F5 钉在 `ca50ab7`（push `35073693026` / PR `35073696875`）。未做生产库写入，未清空数据，未自动合并，未标 ready。

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
| 现有测试 + 新矩阵 + CI | 满足 | 本地 `d83aa32`：779 passed。CI `d83aa32` push `35076660156` / PR `35076663889`：success。后端 776 passed；隔离 12 passed；Docker 镜像步 success；Playwright 3 passed |
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
