# 迁移判断：option-pro → Optix Japan

> 基于 2026-08-02 对旧仓库（FastAPI ~77k 行 + React 19 前端）的全面审阅。
> 原则：领域正确性优先；只搬真正成熟且与市场无关的底座；日股领域全部重建。

## 一、可复用（近似原样移植）

| 模块 | 旧位置 | 判断依据 |
|---|---|---|
| 双 env 纪律（machine.env/secrets.env 键归属） | `runtime_environment.py` | 放错文件的键被忽略而非生效，防静默错配 |
| 单根数据目录 | `data_paths.py` | 冻结 dataclass + 绝对路径校验 |
| 请求安全（可信代理解析） | `services/request_security.py` | 从右往左走 XFF、只信任白名单代理 |
| 部署边界fail-closed校验 | `deployment_boundary.py` | 绑定非环回时强制 ALLOWED_HOSTS 等 |
| 所有者访问（password/private_network + 同源写保护） | `access.py` | PBKDF2-600k、单会话、登录节流、四重同源检查；**剥离顾客账号体系**（本项目纯私有部署） |
| 指纹快照读缓存 | `services/snapshot_read_cache.py` | fstat(fd) 身份 + 按身份负缓存 + single-flight，全项目最佳模块 |
| ETag/304 字节复用 | `services/http_read_cache.py` | 版本键契约 + to_thread 冷编码 |
| 进程内 TTL 缓存 / 缓存指标 | `services/cache.py` / `cache_metrics.py` | 双预算、single-flight；零依赖计数器 |
| SQLite 在线备份 | `tools/sqlite_backup.py` | Backup API + 校验 + 清单 + 保留代 |
| 进程文件锁 + 围栏令牌租约 | `worker/lock.py` + `state.py` | flock 证死 + fencing token 拒僵尸写 |
| Worker 监督器骨架 | `worker/runtime.py` | 每任务独立 asyncio 循环、心跳线程、失败退避、fail-fast |
| AI 任务契约纪律 | `services/ai_jobs/*` | request_hash 折叠提示词/schema 版本、令牌预算、冷却、unknown 提交隔离（双车道+分窗口）、严格 schema、结果审计 |
| 前端底座 | queryRegistry/persistedCache/client/usePolling/remoteState/useAccess | 共享查询注册表 + ETag 304 + 世代计数，最有价值的前端资产 |
| 设计系统 | index.css + tailwind.config | 纸面/墨色/群青语言，与市场无关 |
| 共享组件 | DataTable/StatCard/ChangeBadge/Skeleton/EmptyState/PageHeader/Segmented/InfoHint/Sparkline/ReactECharts/chart.ts | 全部通用 |
| i18n 内核 | `i18n/core.ts` | msgid=中文源串；ja 已是一等语言；AI 文本不过 t() |
| Mock 架构 | `mockOr` + 种子 RNG + stripMocksFromLiveBuild | live 构建用 TS 编译器 API 剥离夹具 |
| 雷达内核 | lifecycle.py 状态机 / scoring.py 缺失感知加权 / base_detector.py 枢轴聚类 | 与市场无关的算法资产；权重重校准 |
| CI/部署形态 | compose 守卫、字节闸门、静态断言、真后端 Playwright | 结构照搬，内容换日股 |

## 二、需要日股化改造

- **format.ts**：America/New_York×5 处 → Asia/Tokyo；en-US → 按语言 locale；T/B/M/K → 兆/億/万；美元 → 円（整数为主）
- **市场日历**：NYSE 硬编码 → J-Quants `/markets/calendar`（HolDiv 1/2 为交易日）
- **会话模型**：premarket/regular/afterhours → 前場(9:00-11:30)/昼休み/後場(12:30-15:30)/大引け後；v1 仅日线，会话仅用于展示
- **雷达数据流**：TradingView 发现 + Yahoo 盘中确认 → **本地全市场日线扫描**（收盘后批处理，数据在自己库里，无第三方发现层）
- **筛选器**：内存 theme 扫描 → SQL 驱动的每日截面快照表
- **指数带**：SPX/NDX/VIX → TOPIX/日经225/グロース市场指数等
- **新闻系统**：MacroLens 外部 ETL → 自建抓取层（RSS 适配器）+ 实体目录（上市主数据+别名）；变更日志/去重/审计纪律保留
- **AI 语言契约**：单一 zh 输出 → 翻译=ja-JP、影响分析=zh-CN 两类任务、独立 schema/版本/指纹

## 三、彻底删除（不迁移）

- 期权全家：期权链、IV、Greeks、到期日、行权价、unusual 扫描、`options.py`、OptionsPanel、IvPanel
- 美股会话：premarket/postmarket、PREMARKET_GAP/GAP_AND_GO/GAP_HOLD/GAP_FADE 生命周期分支
- 美股提供商：Finnhub、FMP、MarketData.app、Massive、Yahoo/yfinance（含 curl_cffi monkey-patch）、Stooq、TradingView
- 美股宏观模块：FRED 30 因子（架构思想保留，未来日本市场内部结构模块参考其 FactorSpec/validate_registry 设计）
- MacroLens ETL 客户端/同步
- 顾客账号体系（accounts.db、注册/登录、30 天会话）——本项目仅所有者
- 美股行业映射（24 themes/GICS/SPDR）、SPY/QQQ 基准、`^`前缀指数符号
- 旧数据库与迁移（optix.db v1→v3 等）：新库全新 schema，无历史包袱

## 四、重新设计（日股领域新建）

- `providers/jquants`：V2 認証(x-api-key)、限流令牌桶(100/min + fins 50/min)、翻页、批量CSV回填、字段映射、能力声明
- `domain`：Issuer/Security 分离、SymbolNormalizer（5位 canonical / 4位 display）、市场区分/33业种常量、交易日历
- `repositories`：jp-core.db 全新 schema（master/calendar/bars/indices/fins/earnings/margin/shorts/radar/sync_state），幂等 UPSERT、检查点、数据新鲜度
- `services`：market(TOPIX/广度/业种)、screener(截面快照)、stock_research、earnings、radar(日线信号引擎)、data_status
- `worker/tasks`：JST 调度（17:00 日线批、18:30 财报速报、25:00 确报补扫、周二信用、周四投资部门别），以交易日历为闸门
- 新闻实体目录：证券代码/日文正式名/簡称/英文名/别名 → security_id
- 盘中扩展点：IntradayQuoteProvider/IntradayBarProvider/RealtimeRankingProvider 协议 + DisabledProvider

## 五、v1 有意缩减（诚实记录）

- 简体中文校验器（旧 ~2000 行 + Unihan 表）→ v1 轻量版（CJK 占比 + 日文假名比例校验翻译）；契约版本号独立，后续可加严
- 投资部门别(investor-types)、EDINET 三表：Standard 可用但 v1 不接，能力声明中标记 planned
- 顾客账号、每分钟线、TDnet 全文：不做
- 走查式回测(walk-forward)框架：v1 保留点时语义与可回放存储，不搬完整验证管线
