# 第十三轮交付报告 — GPT-5.6 Pro 审阅回应

分支 `short-monitor`。对象是审阅针对 `00eb0a5` 提出的 7 个 P0、8 个高优先级
问题与验证方法批评。**逐条核实后再动手** —— 全部先在代码里确认了指出的行为
确实存在（或不存在），下表是核实结论与处置。

---

## 0. 一句话

审阅的绝大多数指控**属实**，已修；一条（P0-7 访问级别）按事实推回；
验证的重跑因需要生产环境的 10 年数据库，交付为**已升级的验证器 + 生产
运行手册**（本机没有全量数据，跑不了）。

---

## 1. P0 逐条

| # | 指控 | 核实 | 处置 |
| --- | --- | --- | --- |
| P0-1 | 验证失败的模型仍在重排雷达 | **属实**：`overlay()` 无条件加 ±8 | `PRIORITY_LINK_ENABLED = SCORE_VALIDATED and GATES_VALIDATED`（现为 False），`priority_shift()` 恒 0；假设值改名 `hypothetical_priority_shift` 仅展示；曾要求"必须改变排序"的 5 个测试改为要求"**不得**改变排序"；overview/status 接口自报 `radar_link.enabled=false`，页面横幅明示 |
| P0-2 | 公开日当日收盘被当作可交易价格 | **属实**：`next_trading_day` 是 bisect_left（含当日） | `first_tradable_day` 改为 bisect_right（**严格次日**）；JPX 当日 16:00 截止公布=收盘后；验证器入场基准改为**次日开盘**（`--entry-basis` 可选 next_close/signal_close 对照）；`VALIDATION` 加 `caveats` 声明旧数字带此偏差 |
| P0-3 | 125 日停更即从合计剔除，硬语义无官方依据 | **属实**（设计取舍，但确实只给了一个口径） | 双口径：`visible_*`（新鲜子集，因子用）+ `reported_in_scope_*`（官方口径：最后报告仍 ≥0.5% 的全部机构）。库、接口、页面、解释文全部两个都出；`exact_position_known` 改名 `exact_at_position_date` |
| P0-4 | 可视合计差把跌破门槛放大成清仓 | **属实**：`_delta(now, prev, "visible_short_shares")` | `window_changes()`：逐（机构×基金）链取两个截止点的现值差再求和。600k→490k 记 −110k（审阅原例已进测试）；再参入按最后可见值为基线；初次披露记全量；粗增/粗减也存入 components |
| P0-5 | 晚发布的旧仓位订正覆盖新状态；订正被计为行为 | **属实**：单键 max(published, position) | 两段选择：同 (链, 仓位日) 内取截止前最新公开版，再于有效版中取**仓位日最新**；订正不进 entry/reduction 等行为计数（单独计 correction） |
| P0-6 | 快照分批写，崩溃暴露半张榜 | **属实**：2000 行/批多事务 | `publish_short_behavior_day()`：全行+信号+run 标记一个 `BEGIN IMMEDIATE`；`short_monitor_runs` 每日一行，run_id 进 ETag（同日重算不再 304） |
| P0-7 | 空卖接口对匿名公开，应 Owner-only | **推回**：`short_monitor` 与雷达/筛选/强度/研究**同一个访问类** `_PUBLIC_READ`（main.py 里 12 个只读模块全部如此）。这是第五轮定下的站点形态：只读公开 + 写操作/自选走账号。单独收紧一个模块反而不一致；若要全站私有，是站点级 access mode 一行切换，不是本模块补丁 | 不改；在此文档记录论据 |

## 2. 高优先级逐条

| # | 指控 | 核实 | 处置 |
| --- | --- | --- | --- |
| 高-1 | 名称规范化过度（International/Securities/Capital/证券/银行/信托 都剥） | **属实**：`Barclays Capital Securities Ltd`→`barclays`；MS 英国/美国法人合并 | 后缀表收紧到纯法人形式（ltd/plc/llc/株式会社…）；同名多住址的名字用住址指纹分实体（两遍扫描，顺序无关）；inst-v1→v2；新增 4 个测试 |
| 高-2 | 生表主键畳掉同日多基金行 | **属实**：PK 缺 fund/address | v8 迁移重建 `short_positions`，PK 加 `investment_fund_name, holder_address`（NOT NULL DEFAULT ''）；event_id 种子加 fund/address/manager；**已畳掉的行本机无法恢复——生产需重拉一次空卖档案**（见 §5 手册） |
| 高-3 | "全量重建"只 UPSERT，幽灵行 | **属实** | `build_version` 印全行，重建末尾 `sweep_short_monitor_build()` 清掉非本轮行（curated 别名除外）；测试：删原始行→重建→导出行归零；curated 存活 |
| 高-4 | 挤空文档说双窗、代码 min() 单窗 | **属实** | `decreasing_both`（双窗）给挤空；回补启动保留单窗（本来就设计如此）；挤空另要求**对 TOPIX 与对行业两个数据都存在**且都转强；sbs-v1→v2；两个新测试 |
| 高-5 | 5 日压力复用 20 日事件计数 | **属实** | `counts_5` / `counts_20` 分开算，5 日压力吃 5 日计数 |
| 高-6 | 缺失比例=closed | **属实**：`visibility_of(None)→closed` | 新增 `unknown` 可视性 + `EVENT_UNKNOWN`；不进任何合计与行为计数；置信度打 0.85 折（`unreadable_report_rows`）；页面标「状态未知」 |
| 高-7 | 置信度取全历史最低映射置信度 | **属实** | 改为「当前持仓机构 + 窗内事件」的最低值（`_current_mapping_confidence`）；五年前一条模糊表记不再永久拖低 |
| 高-8 | 同日重算 ETag 不变 | **属实**：ETag 只有日期+参数+算法版 | rankings/stock/overview 的 ETag 加 run_id（见 P0-6） |

## 3. 验证方法批评的回应

| 批评 | 处置 |
| --- | --- |
| 训练窗没参与训练，不是真走步校准 | **承认**，`POINT_IN_TIME_LIMITS` 明写「固定参数的窗别稳定性报告，非走步校准」 |
| 每 20 日采样 + 池外状态丢失 → 伪状态转换 | 修：`previous_states` 池外保留（`.update()` 不覆盖）；`--every` 默认 1（逐日）；chunk 自适应放大避免 200+ 次读库 |
| 行业中位取自回放子集 | 修：`MarketInputs.sector_median_5d/20d` 可注入，回放从**全市场**足算（生产路径不变，本来就传全市场） |
| 行业超额字段恒空 | 修：`excess_sector_*` 由回放器按**入场日对齐**的收盘算（33 业种成员前向中位，带缓存） |
| 入场应次日开盘 + 报滑点 | 修：`compute_outcome(entry_basis=...)` 支持 next_open（默认）/next_close/signal_close；`--slippage-bps` 单边扣减 |
| 宽泛 absorption 被否 ≠ 原案窄组合被否 | **承认并落实**：回放器新增 A–D 队列（增空不跌 → +深度低位 → +新进/再进 → +回补开始），按「条件由假变真」记一次信号，独立汇报。**E（+突破确认）测不了**——回放不重建雷达，报告里明写"未验证≠被否定" |
| 匹配基准（流动性/波动率/回撤配对） | **未做**，此轮范围外，记入 §6 |

## 4. 版本与迁移

- `inst-v2 + evt-v3 + sbf-v1 + sbs-v2 + sbscore-v1`（快照版本串自动变化 → 全部重建）
- schema `jp-core-v7 → v8`：生表 PK 重建（fund+address 入键）、事件/last_known/实体/别名加 build_version、last_known 加 in_scope/链内订、快照加 reported_in_scope_* 与 unknown 计数、新表 `short_monitor_runs`
- API `jp-short-monitor-v1 → v2`：新增 `reported_in_scope_*`、`unknown_institution_count`、`radar_link`、`chain_count`、`investment_fund_name`；改名 `exact_position_known → exact_at_position_date`

## 5. 生产运行手册（本机做不了的部分）

本机没有 10 年全量库，以下在生产（74.91.31.186 /opt/jp-option-pro）执行：

```bash
# 1) 部署（迁移在容器启动时自动跑；v8 生表重建约数十秒）
./scripts/deploy.sh

# 2) 多基金行审计：v8 主键只能保护今后的写入，已被 v7 主键畳掉的行要重拉。
#    先看畳损规模（fund 名非空行数 vs 预期 ~2,094）：
docker exec -it optixjp-backend python - <<'EOF'
from app.data_paths import get_data_paths
from app.repositories.core import CoreRepository
core = CoreRepository(get_data_paths().core_db, read_only=True)
with core.read() as c:
    print("fund rows:", c.execute("SELECT COUNT(*) FROM short_positions WHERE investment_fund_name != ''").fetchone()[0])
    print("total:", c.execute("SELECT COUNT(*) FROM short_positions").fetchone()[0])
EOF

# 3) 重拉空卖档案：把 bulk 检查点里的窗起点抹掉即可 —— worker 看到
#    bulk_history_from 与当前窗不一致就会重建计划、重新下载 142 个月度
#    文件（v8 主键下多基金行不再被畳掉；约 2h，跑在 worker 里无需盯守）
docker exec -it optixjp-backend python - <<'EOF'
import json
from app.data_paths import get_data_paths
from app.repositories.core import CoreRepository
core = CoreRepository(get_data_paths().core_db)
with core.write() as c:
    row = c.execute("SELECT checkpoint_json FROM sync_state WHERE dataset='reported_short_positions'").fetchone()
    cp = json.loads(row[0] or '{}') if row else {}
    cp.pop('bulk_history_from', None); cp.pop('bulk_done', None); cp['bulk_pending'] = None
    c.execute("UPDATE sync_state SET checkpoint_json=? WHERE dataset='reported_short_positions'",
              (json.dumps(cp),))
print('checkpoint reset:', cp)
EOF

# 4) 全量重建导出物 + 当日快照（evt-v3 语义）
docker exec -d -w /app -e PYTHONPATH=/app optixjp-backend python - <<'EOF'
from app.data_paths import get_data_paths
from app.repositories.core import CoreRepository
from app.services.short_monitor import pipeline
core = CoreRepository(get_data_paths().core_db)
print(pipeline.rebuild_events(core, progress=print).as_dict())
print(pipeline.refresh_snapshots(core, progress=print).as_dict())
EOF

# 5) 重新验证（逐日、次日开盘、全市场行业基准、A–D 队列；预计数小时，务必 -d）
docker exec -d -w /app -e PYTHONPATH=/app optixjp-backend \
  python -m app.research.short_behavior_runner \
    --start 2017-01-01 --end 2026-06-30 --every 1 \
    --entry-basis next_open --slippage-bps 20 \
    --out /data/short-behavior-report-v2.json
```

跑完后把 §十六 四问的新答案、A–D 队列结果与 `VALIDATION` 常量一起更新
（在那之前 `VALIDATION.caveats` 声明旧数字的三个已知偏差）。

## 6. 明确没做的

- **验证重跑本身**（需生产数据，手册见上）。当前页面横幅仍显示第十二轮
  的否定结论 + caveats —— 旧结论的方向（未通过）在语义修正后大概率不变，
  但幅度数字不能再被引用为精确值。
- 匹配基准（同流动性/波动率/回撤分层的对照组）。
- 队列 E 与挤空确认的验证（要求雷达在回放内重建）。
- 市场区分/行业的点时化（沿用现值，`POINT_IN_TIME_LIMITS` 已声明）。
- 信用余额进回放（`crowded_margin` 在回放中仍恒不触发，已声明）。

## 7. 测试

392 → **413**（全部通过）。新增覆盖：严格次日效力、订正两段选择、跌破
门槛差值（审阅原例 600k→490k）、再参入基线、多基金链求和与不交叉、双口径
合计、unknown 可视性、同名分址、业务词保留、挤空双窗+双基准、雷达联动
禁用（5 个反向断言）、原子发布 run 换代、幽灵行清扫、curated 存活、
多基金生表主键。
