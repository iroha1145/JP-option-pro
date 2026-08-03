# J-Quants API V2 调研笔记（Standard 套餐）

> 调研日期：2026-08-02，来源：jpx-jquants.com 官方 V2 文档。
> 实现以此为准；旧 V1（token 认证、/v1/* 端点）已于 2026-06-01 停用，禁止实现。

## 基础

- Base URL: `https://api.jquants.com/v2`
- 认证：HTTP 头 `x-api-key: <API KEY>`（从 Dashboard 签发；环境变量 `JQUANTS_API_KEY`）
- 响应：JSON，`{"data": [...], "pagination_key": "..."}`；支持 gzip
- 翻页：响应含 `pagination_key` 时，携带同参数 + `pagination_key` 继续请求，直到响应不含该字段
- 限流：Standard 全局 **120 req/min**；`/fins/summary`、`/fins/details` 单独 **60 req/min**
- 超限返回 **429**（文档未承诺 Retry-After）；严重超限会被封禁约 5 分钟 → 客户端必须自行节流
- 日期参数格式：`YYYY-MM-DD` 或 `YYYYMMDD`

## Standard 套餐可用端点（历史 10 年）

| 数据集 | 端点 | 说明 |
|---|---|---|
| 上市证券主数据 | `/equities/master` | Date, Code, CoName, CoNameEn, S17/S17Nm, S33/S33Nm, ScaleCat, Mkt/MktNm, Mrgn/MrgnNm, ProdCat |
| 日线四本值 | `/equities/bars/daily` | 见下方字段表 |
| 财务摘要 | `/fins/summary` | 见下方字段表；**限 60/min** |
| 决算发表预定日 | `/equities/earnings-calendar` | 仅直近；**仅 3 月期/9 月期决算公司**；不含 REIT |
| 交易日历 | `/markets/calendar` | Date, HolDiv；参数 hol_div/from/to |
| 投资部门别 | `/equities/investor-types` | 周度 |
| TOPIX 四本值 | `/indices/bars/daily/topix` | |
| 指数四本值 | `/indices/bars/daily` | 部分指数仅收盘价（O/H/L 为 null） |
| 信用取引周末残高 | `/markets/margin-interest` | 周度 |
| 日々公表信用取引残高 | `/markets/margin-alert` | 日度（被公表/规制的个股） |
| 业种别空卖比率 | `/markets/short-ratio` | 按 33 业种日度 |
| 空卖残高报告 | `/markets/short-sale-report` | ≥0.5% 大额空头持仓报告 |
| 大株主状况 | `/edinet/major-shareholders` | EDINET 来源 |
| 政策保有株式 | `/edinet/cross-shareholdings` | EDINET 来源 |
| 大量保有报告书 | `/edinet/large-volume-shareholders` | EDINET 来源 |
| 日经225期权 | `/derivatives/bars/daily/options/225` | **本产品不使用（非期权工具）** |

## Standard 不可用（必须在能力声明中标记 unavailable）

- `/fins/details` 财务诸表详细（Premium）
- `/fins/dividend` 配当金信息（Premium）
- `/markets/breakdown` 卖买内訳（Premium）
- `/equities/bars/daily/am` 前场四本值（Premium）
- `/derivatives/bars/daily/futures`、`/derivatives/bars/daily/options`（Premium）
- `/equities/bars/minute` 分钟线（加购，60/min）
- **tick（加购）没有 REST 端点**：官方仅以 CSV 一括配信提供 —— `/bulk/list?endpoint=equities/trades` 列文件 → `/bulk/get` 取预签名 URL。字段 `Date,Code,Time(微秒),SessionDistinction(01前場/02後場),Price,TradingVolume(单笔),TransactionId`；过去 2 年、仅东证上市。日次全市场 50–70MB gz / 约 650 万行
- ⚠️ 该网关对**任何未知路径**都返回 403 `plan_not_included`，因此 403 不能用来判断「是否已加购」——我曾据此误判 tick 未激活
- TDnet 全文（`/td-*`，加购，100/min）
- `fins/summary` 的 `cursor` 增量参数（Premium 专属）→ Standard 用 date 查询做增量

## `/equities/bars/daily` 字段

| 字段 | 含义 |
|---|---|
| Date, Code | 交易日、证券代码（5 位字符串） |
| O, H, L, C | 未复权四本值（当日无成交为 null） |
| UL, LL | 涨停/跌停标志（"0"/"1"） |
| Vo, Va | 成交量、成交额（円） |
| AdjFactor | 复权系数（如 1:2 拆分 → 0.5，作用于当日以前） |
| AdjO, AdjH, AdjL, AdjC, AdjVo | 复权后四本值与成交量 |
| M*/A* 前缀 | 前场/后场数据 —— Premium 专属，Standard 下为 null，勿用 |

## `/fins/summary` 关键字段（缩写名）

- 期间：DiscDate, DiscTime, DiscNo, CurPerType(1Q/2Q/3Q/FY), CurPerSt, CurPerEn, CurFYSt, CurFYEn, NxtFYSt, NxtFYEn
- 实绩（连结）：Sales, OP(营业利益), OdP(经常利益; IFRS/US-GAAP 下可能为空), NP(纯利益), EPS, DEPS
- 资产负债：TA, Eq, EqAR(自己资本比率), BPS；现金流：CFO, CFI, CFF, CashEq
- 配当实绩：Div1Q..DivFY, DivAnn, DivUnit, DivTotalAnn, PayoutRatioAnn
- 配当预想：FDiv*（当期）、NxFDiv*（翌期）
- 业绩预想：FSales2Q/FOP2Q/FOdP2Q/FNP2Q/FEPS2Q（中间期）；FSales/FOP/FOdP/FNP/FEPS（期末）；NxF*（翌期）
- 修正与旗标：MatChgSub, SigChgInC, ChgByASRev, ChgNoASRev, ChgAcEst, RetroRst
- 股数：ShOutFY, TrShFY, AvgSh
- 单体（非连结）：NC 前缀（NCSales, NCOP, NCOdP, NCNP, NCEPS, ...）；预想 FNC*

## 信用/空卖字段

`/markets/margin-interest`（周度，申込日）: Date, Code, ShrtVol, LongVol, ShrtNegVol, LongNegVol, ShrtStdVol, LongStdVol, IssType(1 信用/2 貸借/3 其他)

`/markets/margin-alert`（日々公表）: PubDate, AppDate, Code, ShrtOut, LongOut, SLRatio(取组比率), ShrtOutChg, LongOutChg, ShrtOutRatio, LongOutRatio, ShrtNegOut, ShrtStdOut, LongNegOut, LongStdOut, TSEMrgnRegCls(东证规制区分), PubReason(公表理由旗标组)；订正以同 AppDate 追加记录方式发布

`/markets/short-ratio`（业种日度）: Date, S33, SellExShortVa(非空卖), ShrtWithResVa(有价格限制空卖), ShrtNoResVa(无价格限制空卖) —— 均为成交额

`/markets/short-sale-report`: DiscDate, CalcDate, Code, SSName, SSAddr, DICName, DICAddr, FundName, ShrtPosToSO(空头持仓比), ShrtPosShares, ShrtPosUnits, PrevRptDate, PrevRptRatio, Notes

## 批量下载（历史回填首选）

1. `GET /v2/bulk/list?endpoint=/equities/bars/daily`（或 `date=YYYY-MM`；endpoint 模式可加 from/to）
   → `[{Key, LastModified, Size}]`，文件按年月切分
2. `GET /v2/bulk/get?key=<Key>` → presigned URL
3. 下载 gzip CSV 解析入库
- 交易日历只返回最新一个文件
- Free 套餐无 CSV；Standard 可用，数据范围同 API（10 年）

## 官方更新时间（JST，近似值，可能变动）

| 数据 | 时间 |
|---|---|
| 日线/指数/margin-alert/short-ratio | 每交易日 ~16:30 |
| fins/summary | 速报 18:00；确报 ~24:30（披露高峰可能延迟） |
| earnings-calendar | 翌营业日信息 |
| margin-interest | 每周第 2 营业日 16:30 |
| investor-types | 每周第 4 营业日 ~18:00 |
| EDINET 三表 | 平日 8:00–17:59 随时 |

→ Worker 调度基线：**17:00 JST 日线批**、**18:30 JST 财务速报批**、**25:00(次日 01:00) JST 财务确报补扫**，每周二 17:30 信用残高、每周四 18:30 投资部门别。全部以交易日历为闸门。

## 市场区分代码（Mkt）

0111 プライム / 0112 スタンダード / 0113 グロース / 0105 TOKYO PRO MARKET / 0109 その他；
旧区分（2022-04 之前的历史数据）：0101 东证一部 / 0102 二部 / 0104 マザーズ / 0106 JASDAQ スタンダード / 0107 JASDAQ グロース

## 主要指数代码

- 0000 TOPIX；0500/0501/0502 プライム/スタンダード/グロース市场指数；0070 旧マザーズ指数
- 规模：0028 Core30, 0029 Large70, 002A TOPIX100, 002B Mid400, 002C TOPIX500, 002D Small
- 风格：8100 TOPIX Value, 8200 TOPIX Growth；REIT：0075（细分 8501/8502/8503）
- 33 业种各自有指数代码（如 0046 化学、004F 电气机器、005B 银行业），全表见官方 indexcodes 页

## 实现纪律

- 证券代码一律字符串；J-Quants 为 5 位内部码（常见 4 位代码 + 检查位），显示层用 4 位 display_code，但主键用 canonical_code(5 位)
- 提供器层做字段名映射（缩写 → 领域字段），J-Quants 缩写名不得泄漏到 repository 之外
- 客户端内置令牌桶限流（保守：100/min 全局 + fins 50/min），429 时指数退避 + 尊重封禁窗口
- 已完成交易日数据视为不可变；官方修订通过 as_of/ingested_at 版本化受控覆盖
