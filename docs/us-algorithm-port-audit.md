# 美股算法迁移审计矩阵

对象：`iroha1145/option-pro`（美股，参考只读） → `iroha1145/JP-option-pro`（日股，正式）

审计日期：2026-08-03 ／ 参考仓库提交 `9e8ab64`

判断原则（doc §四）：**数学骨架可以搬，市场常数不能搬。**
只迁移「J-Quants 现有数据能正确实现、能回测、能解释」的模块。

---

## 0. 结论速览

| 处置 | 模块数 | 说明 |
|---|---|---|
| 已迁移，无需重做 | 11 | 日股版已有等价实现 |
| 本轮迁移 | 1 | 市场状态门控（含迟滞） |
| 建议迁移，待数据 | 3 | 需要日股专属基准或历史验证 |
| 不迁移（美股专属） | 6 | 依赖美股数据源或美股结构 |
| 不迁移（已有更好实现） | 2 | 日股版本已优于参考实现 |

---

## 1. 已迁移，无需重做

| 美股模块 | 算法目的 | 日股对应 | 备注 |
|---|---|---|---|
| `breakouts/base_detector.py` | 枢轴聚类与平台检测 | `radar/base_detector.py` | 同形。日股版已排除当日（先读禁止） |
| `breakouts/lifecycle.py` | 突破状态机 | `radar/lifecycle.py` | 本轮修复跳空转移；日股去掉了美股盘前分支 |
| `breakouts/scoring.py` | 缺失感知加权 | `radar/scoring.py` | `weighted_score` 同形，缺失按权重剔除而非填 50 |
| `breakouts/feature_engine.py` | 多周期特征 | `radar/features.py` | 成交额改日元口径 |
| `breakouts/breakout_detector.py` | 突破信号识别 | `radar/engine.py:detect_new_signal` | 优先级序列同形 |
| `breakouts/relative_strength.py` | 相对强度 | `radar/engine.py` + `screener.py` | 基准 SPY→TOPIX；本轮拆分 20d/63d |
| `strength/price_action.py` | HH/HL 结构、Spring/Upthrust | `radar/price_action.py` | 同形 |
| `strength/vol_price_match.py` | 量价一致性（Wyckoff） | `radar/vol_price_match.py` | 同形 |
| `technical/range_persistence.py` 部分 | 波动收缩 | `radar/features.py:volatility_contraction` | 仅收缩部分；完整 Range Persistence 见 §3 |
| `strength/scanner.py` | 横截面强度扫描 | `services/strength_scan.py` | 本轮重构（风险减分入排序、去重复计权） |
| `macro_conditions/` | 宏观分位 | 已在日股版存在 | 见 `optix-macro-conditions` |

---

## 2. 本轮迁移

### 2.1 市场状态门控 + 迟滞（`strength/market_shape.py` → `services/market_shape_jp.py`）

**为什么值得搬**：日股版 `compute_market_regime_jp` 每天从零重算一个分数，
**没有迟滞**。分数在阈值附近摆动时状态天天翻转；一旦状态用于门控确认要求
（doc §七正是要这么做），整个雷达的判定标准就跟着天天变。美股版有
`ENTER_CONFIRM_DAYS` / `EXIT_CONFIRM_DAYS` / `MIN_DWELL_DAYS` 三道迟滞，
这部分是**市场中性的状态机数学**，可以直接搬。

**搬什么 / 不搬什么**：

| 项目 | 处置 |
|---|---|
| 六状态划分（多头趋势/多头回调/区间蓄势/区间派发/空头趋势/恐慌修复） | ✅ 搬（概念市场中性） |
| 进入/退出确认天数、最短停留天数 | ✅ 搬（迟滞机制本身） |
| 每状态的确认要求增减（`confirmation_bar_delta`） | ✅ 搬结构 |
| 各状态的 `ordinary_breakout_fit` 数值（88/62/72/36…） | ❌ 不搬。美股调出来的数，日股没有证据 |
| `OPENING_RANGE_BREAKOUT` / `GAP_AND_GO` 设置类型 | ❌ 不搬。日股无盘中数据，开盘区间突破无法实现 |
| `EMERGENCY_BEAR_CONFIG` 阈值 | ❌ 不搬。基于美股波动分布 |

**当前状态**：门控数值标为**未验证**（`validated: false`），走步验证通过前
不得描述为「日股最佳参数」（doc §十五）。

---

## 3. 建议迁移，待数据或验证

| 美股模块 | 算法目的 | 阻塞原因 | 前置条件 |
|---|---|---|---|
| `technical/range_persistence.py` 完整版 | 区间持续性（Pine 移植） | 日股版只做了收缩部分。完整版含区间年龄、突破后持续性，需要历史验证才知道日股阈值 | 走步验证跑通后校准 |
| `strength/relative_spreads.py` | 风格价差（成长/价值、大盘/小盘） | 美股用 QQQ/SPY/IWM。日股需要等价基准：Prime/Standard/Growth 指数或 TOPIX/Core30 | 需确认 J-Quants 指数代码覆盖（当前只验证了 0000 TOPIX、0028 Core30） |
| `breakouts/range_interactions.py` | 区间交互（回踩/再加速的量化形式） | 依赖上面的 Range Persistence 完整版 | 同上 |

---

## 4. 不迁移（美股专属）

| 美股模块 | 不迁移的原因 |
|---|---|
| `strength/yahoo_options.py` | 期权链与隐含波动率。日股个股期权流动性极低，无可用数据源 |
| `strength/finnhub.py` | 美股数据商，日股无覆盖 |
| `services/yahoo.py` / `yfinance_batch.py` | 美股行情适配。日股已用独立的遅延气配提供器层 |
| `breakouts/clock.py` 盘前/盘后分支 | 美股 pre/post market 结构。东证无盘前盘后连续交易 |
| `catalysts/economic_calendar_actuals.py` | 美国经济指标日历 |
| `strength/market_regime.py` 的 VIX 依赖 | 日股无等价的低成本恐慌指数实时源（日经VI 非免费） |

---

## 5. 不迁移（日股版已更好）

| 美股模块 | 日股版为何更好 |
|---|---|
| `breakouts/research.py` + `research_validation.py`（1,993 行） | 日股版 `app/research/`（1,129 行）把点时闸门收敛到 `bars_up_to()` 单点，并强制「追加未来数据后过去评价不变」的测试。美股版把点时标签散在多处，且 forward price 需外部离线数据集 |
| `breakouts/repository.py`（3,510 行） | 日股版仓储按数据集拆分，且有前向迁移链（v1→v4）。美股版单文件承担全部读写 |

---

## 6. 日股独有（美股版没有，本轮新增）

这些不是迁移，是日本市场特有的东西：

| 模块 | 为什么美股版没有 |
|---|---|
| `services/margin_regulation.py` | 日々公表・増担保・日証金规制。美股无对应制度 |
| `radar/turnover_quality.py` | 成交额稳健统计。美股版 `turnover_stability` 同样是「字段存在即 100」，本轮日股先修（美股版仍有此缺陷） |
| `services/tick_analytics.py` | J-Quants Tick CSV。美股版用不同的数据形态 |
| `strength_scan.py:lot_fit` | 日本股 100 股单元制，最低购入金额是真实的可交易性维度 |

> **反向建议**：`turnover_stability` 恒返回 100 的缺陷在美股仓库中仍然存在
> （`strength/scanner.py`）。若两边要保持一致，应把日股版的稳健统计回搬。

---

## 7. 迁移时必须做的事（doc §四）

每次从美股仓库搬代码，逐条确认：

1. 去除美股数据依赖（SPY/QQQ/VIX/GICS/SPDR）
2. 替换市场特有常量（美元阈值 → 日元；美股波动分布 → 日股分布）
3. 加入日股测试
4. 不破坏点时语义
5. 记录来源与差异（本文件）
6. 不复制死代码和历史兼容层

---

## 8. 未解决的真实限制

- **风格价差**缺日股基准：只确认了 TOPIX(0000) 与 Core30(0028) 两个指数有数据。
  Growth/Standard 的指数代码未确认，`2516.T` 跟踪的是 Growth **250**（另一个指数），
  不能当作 Growth 全体的代理。
- **市场状态门控数值**目前无历史证据，标为未验证。
- **业种/市场区分**只有当前断面（见 `app/research/replay.py:POINT_IN_TIME_LIMITS`）。
