# 美股 A0/T1 / 网页优化 → 日本站迁移清单

执行时固定基线（2026-09-16 fetch）：

| 项 | SHA |
|---|---|
| TARGET_BASE_SHA（日本站 `origin/main`） | `a449ddb9ee89785eae22ea4c28174903c89d331c` |
| 任务书记载的日本站参考点 | `a449ddb9ee89785eae22ea4c28174903c89d331c`（一致） |
| SOURCE_SHA（美股 PR #167 合并提交） | `98330ca4dc27af5e640484b3797ee7aa3d6f1573` |
| 美股 `origin/main`（核对用，不自动纳入） | `8b620d760f05020d2c1b51a3c3228a89fd9f3120` |
| 必须包含的修复 | `6b0cb414` 不完整输入不覆盖 settled；`61f50758` 派发前持久化预约次数 |

`61f50758` 是 `98330ca` 的祖先。`8b620d76` 相对 `98330ca` 还有后续无关提交（例如 #171 杠杆 ETF），**不纳入**本次移植。

日本站算法版本号使用 `jp-*` 前缀，不用美股 `a0-mid-long-v1` / `t1-daily-priority-v1`，避免暗示底层输入完全相同。

## 映射

| 来源行为（option-pro @ 98330ca） | 日本站现有入口 | 复用 / 适配 / 不迁移 | 测试 ID |
|---|---|---|---|
| A0 = 0.5×score_mid + 0.5×score_long；None/NaN/Inf 不可算；零分合法 | `strength_scan.score_mid/score_long` 已由夜间批次写入；`/api/strength/scan` 对全池筛选后再排序 | **适配**：请求时对已保存断面排序，不重算家族、不另存 A0 快照、不建每用户重扫队列 | `test_a0_math.py` / `test_a0_api.py` |
| A0 仅 timeframe=all + profile=balanced；显式冲突 400/422 | `TIMEFRAMES` / `PROFILES`；页面 94%/6% 混合键是短/中/长期视图，不是 A0 | **适配**：非法组合结构化错误，UI 禁用 | `test_a0_api.py` / `algorithm-a0-t1.test.mjs` |
| 并列：分数降序 + ticker 降序 | `sort_view_rows` 分数降序 + `canonical_code` 降序 | **复用**日本站代码序作为最终键 | `test_a0_math.py` |
| 全不可算时不可宣称 A0 已生效 | 无 | **适配**：`a0_unavailable`，不回退成“已生效的原排序”却贴 A0 标签 | `test_a0_api.py` |
| T1 仅 DAILY_BASE_BREAKOUT | `radar.engine.SIGNAL_BASE_BREAK = base_breakout`；其它 high_break_* / volume_surge_break 保持原优先级 | **适配语义**：只评估首次触发的 `base_breakout`；无冻结平台证据 → `not_applicable` | `test_t1_priority.py` |
| CLV/RVOL/上影/ATR 距；RVOL=成交量中位数；ATR=TR 的 20 日 SMA | `turnover_ratio` 是成交额比；现有 `atr14` 是 14 日特征，不是 T1 ATR | **适配**：独立 T1 数学；成交量走 `adj_volume` / 逆因子调整；禁止 Va 代 Vo | `test_t1_priority.py` / `test_t1_volume_not_turnover.py` |
| 不完整输入只写 latest_attempt；存储层不盲信 identity_complete | 无 T1 表 | **移植最终语义**到 `radar_t1_*`（jp-core-v10）+ 冻结锚位 `radar_t1_anchors`（jp-core-v11） | `test_t1_settled_and_identity.py` / `test_t1_frozen_anchor.py` |
| 派发 `price_data.daily` 前预约 8 次预算 | `worker/runtime.py` 现为 sync `to_thread`，无外层 wait_for 取消 | **适配**：本地日线优先；缺 T 日线才预约后派发；supervisor `wait_for` 取消计入预算 | `test_t1_close_retry_budget.py` |
| 美股每用户 A0 变体文件 / variant_demand 队列 | 日本站夜间全池 + API 轻量筛选 | **不迁移** | — |
| 美股期权 / NY 时区 / SPY/QQQ / 盘前盘后 | 日本站已排除 | **不迁移** | `ci.yml` 美股残留门 |
| 偏好 JSON 文件 + fcntl | `jp-app.db` 是 API 唯一可写应用库 | **适配**：SQLite 原子 UPSERT，不另造文件队列 | `test_view_preferences.py` |
| 前端 queryRegistry 完整算法路径、乱序世代、偏好不阻塞 | Screener 现走裸 `get` + 常 `cache:'reload'`；雷达 `/radar/current` 无算法键 | **适配**：参数化缓存身份；普通切换不 reload；Owner 刷新绑定 publication | `test_http_cache_identity.py` / Playwright E2E |
| 自动画线 / 标注定位 | PR #22–#24 已修好 | **不改** | 现有 chart gates |

## 保留的日本站能力

夜间全池计算、请求时轻量筛选排序、TOPIX 相对强弱、MA25/75/200、33 业种、日元成交额、canonical_code、J-Quants V2、机构空卖/信用规制/新闻/决算/自选/市场/个股、原版默认排序与雷达生命周期。

A0/T1 是可选模式。工程接通 ≠ 已证明日股收益率提高。

## 数据库迁移与回滚

### jp-core-v9 → jp-core-v10

`initialize()` 对已有 `jp-core-v9` 库执行 `_T1_DDL`，新增：

- `radar_t1_evaluations`
- `radar_t1_current`
- `radar_t1_retry`

不改现有 `radar_events` / `strength_rows` / 证券主数据。重复 `initialize()` 幂等。

### jp-core-v10 → jp-core-v11

新增 `radar_t1_anchors`。首次发布 `base_breakout` 时写入冻结阻力（`resistance_high`、平台 ID、调整口径）。`INSERT OR IGNORE`，日常 structure 覆盖不得改锚。

**已经保存的不可靠 T1 版本：** v10 时代用当日 `features.structure.base.resistance_high` 评出的 met/unmet 不能当作历史证据。升级后：

- 有 `radar_t1_anchors` 或事件上已冻结 `t1_anchor` 的，继续用该锚重评；官方 T 日窗口修订可以产生新 `eval_version`，但 `first_known_at` 与锚位不变。
- 没有锚、也没有「当时 pivot 就是阻力且口径一致」的书面恢复记录的，重评结果为 `not_applicable`（`missing_frozen_platform`）。旧 `radar_t1_evaluations` 行保留，不删除、不回写成今天的 structure。
- 不要用生产 `pivot_price` 盲恢复：检测器里的 pivot 是 resistance mid，不是 T1 阻力高。

回滚（仅在确认不再读取 T1 之后）：

1. 将代码回退到 `TARGET_BASE_SHA` `a449ddb9ee89785eae22ea4c28174903c89d331c`。
2. 旧代码打开 v11 库会因版本/校验和不匹配而拒绝启动。需要先把 `jp_core_schema.version` 写回当时的版本并恢复 checksum，或从备份还原整个 `jp-core.db`。
3. 可选：`DROP TABLE radar_t1_evaluations; DROP TABLE radar_t1_current; DROP TABLE radar_t1_retry; DROP TABLE radar_t1_anchors;`
4. **不要**清空 `securities` / `daily_bars` / `strength_rows` / `radar_events`。

生产库约 4GB。禁止用“删库重建”当回滚。

### jp-app-v2 → jp-app-v3

新增 `view_preferences` 与 `algorithm_defaults`。回滚代码后同样需要把 `jp_app_schema` 写回 v2，或还原 `jp-app.db` 备份。可单独 `DROP` 这两张表，不影响自选。

默认算法仍是 `production`。未写偏好的主体等价于 `follow_default`。

## 明确不声称的事项

- 没有日股收益率回测，不能把工程迁移成功写成“已证明日股收益提高”。
- `turnover_ratio` / `turnover_value` 不是 T1 RVOL。
- 15:30 JST 收盘 ≠ J-Quants 已发布。八次预算从 vendor 门（默认 17:00）开始。
