# 第十四轮交付报告 — 空卖监控算法优化（研究结论落地）

对应研究报告《机构空卖行为监控：算法优化研究》（2026-09-02）。这一轮把报告里
P0 全部、P1 中不改变排序语义的部分落成代码；**没有**调任何权重或闸门去拟合
旧回测，也**没有**打开任何会改变雷达排序的开关。

---

## 0. 一句话

数据层不动；因子层加上「informed 口径」（排除国内证券与个人名义的报告主体）
与潜伏空头；状态机的回补开始 / 挤空确认改为要求 informed 口径的减仓；雷达侧
加上「只减不加」的拥挤度叠加，但**闸门关着**，要等验证器新增的窗别判定通过。

## 1. 研究结论 → 代码

| 研究发现 | 落地 | 文件 |
| --- | --- | --- |
| 报告主体之间 20 日超额差 4 个百分点（实体级 p10 −3.7% / p90 +0.3%）；显式「ヘッジ」标注不区分 | `reporter_class`（global_pb / domestic_broker / hedge_fund / market_maker / aggregate / unknown），按实体名判定，不看 Notes | 新 `services/short_monitor/reporters.py`（rep-v2） |
| **类别级校正**（部署后跑 `informedness`）：global_pb −2.27% / market_maker −2.19% / domestic_broker −2.15% / unknown −1.85% / hedge_fund −1.03% / **aggregate −0.39%**。「国内证券 ≈ 0」只对 3 家小样本实体成立，整类被 MS MUFG 証券（27.6 万条）主导 | `INFORMED_CLASSES` **只排除 aggregate**（rep-v1 曾排除 domestic_broker，校正后撤回）；类别保留为描述与校正用元数据，信息量加权走实体级 | `reporters.py` |
| 全鎖口径把信号和噪声等权 | 快照同时产出全鎖口径与 informed 口径的压力、可见机构数、窗内差值、事件计数；写在 `components_json.informed`，**不加 DB 列** | `snapshot.py` |
| 无条件回补事件后 20 日超额 −2.56%，比增仓还差 | `covering_start` 与 `squeeze_confirmed` 额外要求 informed 口径的减少；校正后 informed 只排除个人名义，所以这条闸门目前几乎只挡「個人」单独减仓 —— 机制先落地，实体级加权接上后才有实质筛选力 | `states.py`（sbs-v3） |
| 主动回补与被动回补方向相反（Blocher） | 标签 `voluntary_covering`（回补前 10 日相对收益 ≤ 0）/ `forced_covering`（> 0）；验证器对两者分别汇报 | `states.py`, `snapshot.py`（新增 `rel_topix_10d`） |
| 跌破门槛的 79% 停在 0.45–0.50%（bunching） | `parked_below_count`（60 个交易日内最后报告落在 [0.40%, 0.50%) 的机构数）+ 标签 `parked_below`；`covering()` 的广度项去掉 `threshold_exits` | `factors.py`（sbf-v2） |
| 可见机构数越多越差是唯一稳定单调关系 | 雷达 `crowding_shift`：只减不加（≥2 家 −2、≥4 家 −4，乘置信度，优先用 informed 口径机构数），`CROWDING_LINK_ENABLED = False`；仮の値 `hypothetical_crowding_shift` 在 API 里可见 | `radar_link.py` |
| DTC 分子只有机构可见部分 | `combined_visible_days_to_cover = (机构可见股数 + 信用売残) / ADV20`，写入 components | `factors.py`, `snapshot.py` |
| 验证基准用 TOPIX 会把小盘效应记到信号头上 | 回放新增配对基准 `excess_peer_*`（市场区分 × 流动性五分位的成员前向中位）；`compare_states` 有配对基准时优先用它 | `research/short_behavior_runner.py`, `research/short_behavior.py`（sb-research-v2） |
| 状态转换样本高度重叠、无区间 | 状态别中位数的 95% 区间用「銘柄 × 月」聚类 bootstrap | `research/short_behavior.py` |
| `monitor_priority` 从未做排序力检验 | 逐日十分位单调性（与雷达走步同一套判定） | `research/short_behavior.py` |
| 拥挤度叠加需要窗别稳定性证据 | `crowding_stability`：16 窗中 ≥13 窓「4+ − 0/1」为负且留出期为负才 `pass`；visible 与 informed 两个口径分别判 | `research/short_behavior.py`, runner `--holdout-start` |
| 回放不读信用余额，`crowded_margin` 从未被验证 | 回放按块读取 `margin_interest`，按「申込日 ≤ 评估日 − 2 天」取点时值 | `research/short_behavior_runner.py` |
| 生产 worker 没传 `news_counts`，`news_catalyst` 永不触发 | `_news_counts_5d` 读 jp-news.db 近 5 个交易日记事按证券计数；无新闻源时 `has_news_feed=False` | `worker/tasks.py` |
| 机构命中率需要滚动样本外计算 | 研究 CLI `python -m app.research.informedness`：按事件类型 / 类别 / 增幅 / 仓位 / 实体输出 20 日超额，并列出「名簿外但样本多」的实体供校正 | 新 `research/informedness.py` |

版本串：`inst-v3+evt-v3+rep-v2+sbf-v2+sbs-v3+sbscore-v1`；API `jp-short-monitor-v3`（行新增 `informed` / `parked_below_count` / `reporter_classes` / `combined_visible_days_to_cover`，status 新增 `radar_link.crowding_enabled` / `crowding_validation`）。

## 2. 明确没做的

- 没有改 `WEIGHTS` / `GATES` 的数值；`SCORE_VALIDATED` / `GATES_VALIDATED` 仍为 False。
- 没有打开 `PRIORITY_LINK_ENABLED`，也没有打开 `CROWDING_LINK_ENABLED`。
- 没有做机构命中率**加权**（需要滚动样本外的历史表，先用 informedness CLI 产出材料）。
- 没有引入日証金借券数据；`squeeze_confirmed` 仍只是「空头减少 + 突破确认」，页面上的未验证声明保持。
- 没有在旧回测上调任何东西。

## 3. 生产运行手册

```bash
# 0) 部署后，快照版本串变化，当晚 post_close 自动重建；要立刻看新字段可手动触发
#    （worker 动作队列 short_monitor_refresh）。

# 1) 报告主体信息量（约 1 分钟，逐股 Python，不要用多表 SQL join）
docker exec -d -w /app -e PYTHONPATH=/app jp-option-pro-backend-1 \
  sh -c "python -m app.research.informedness --start 2023-06-01 --out /data/informedness.json > /tmp/informedness.log 2>&1"

# 2) 走步重验证（数小时，务必 -d；SSH 断开会杀非 -d 进程）
docker exec -d -w /app -e PYTHONPATH=/app jp-option-pro-backend-1 \
  sh -c "python -m app.research.short_behavior_runner \
    --start 2017-01-01 --end 2026-06-30 --every 1 \
    --entry-basis next_open --slippage-bps 20 --holdout-start 2025-07-01 \
    --out /data/short-behavior-report-v2.json > /tmp/short-behavior-v2.log 2>&1"

# 3) 读结论：
#    - report.states.by_state.*.median_excess_peer_20d / ci95_excess_peer_20d
#    - report.priority_ranking.verdict
#    - report.crowding.informed.verdict == "pass" 才允许把 CROWDING_LINK_ENABLED 翻 True
#      （同时把 CROWDING_VALIDATION 写成实际数字，页面横幅同步）
#    - report.flags.voluntary_covering / forced_covering 决定回补状态是否保留
```

## 4. 测试

新增 `tests/test_short_monitor_reporters.py`，并在 algorithm / snapshot / radar_link /
research / backfill_window 里加了对应用例：门槛退出不计入回补广度、潜伏空头计数与标签、
informed 口径为空时不触发回补开始、主动 / 被动回补标签、拥挤度叠加只减不加且闸门关闭、
配对基准与 bootstrap、信用余额的点时读取、新闻按证券计数。
