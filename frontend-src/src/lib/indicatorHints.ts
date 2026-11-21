/**
 * 指标与评分说明文案 — InfoHint 的唯一内容来源。
 *
 * 规则（沿袭美版 scoreHints 的纪律）：
 * - 文案必须描述本仓库后端的真实算法（权重/窗口/映射区间与代码一致），
 *   不写愿景、不写代码里没有的东西；算法改了必须同步改这里。
 * - title/body/note 在定义处就地 t()：InfoHint 内部不再翻译。
 */

import { t } from '@/i18n/core';

export interface ScoreHint {
  title: string;
  body: string;
  note?: string;
}

/* ---------------- K线旁的技术指标（个股页右栏） ---------------- */

export const TECHNICAL_HINTS: Record<string, ScoreHint> = {
  rsi14: {
    title: t('RSI 14'),
    body: t('14日 Wilder RSI，衡量近期涨跌动能的相对强弱（0-100）。'),
    note: t('入评分时按折线映射：RSI≈68 得分最高（88 分），30 以下与 80 以上都会降分——动能强但未极端才加分。'),
  },
  macd: {
    title: t('MACD 动向'),
    body: t('MACD(12/26/9) 柱状图最近 3 根的变化量，按收盘价折算成百分比。正值表示多头动能在增强，负值表示衰减。'),
  },
  trend_efficiency: {
    title: t('趋势效率'),
    body: t('Kaufman 效率比：63 日净涨跌幅除以逐日波动路径总长。越接近 1 越接近单边直线行情，接近 0 则为来回震荡。'),
  },
  ma50_slope: {
    title: t('MA50 斜率'),
    body: t('50 日均线在最近 21 个交易日的变化率，衡量中期趋势的方向与坡度。'),
  },
  range_position: {
    title: t('区间位置'),
    body: t('收盘价在最近 60 日高低区间内的位置：0% 贴着区间底，100% 贴着区间顶。'),
    note: t('显示值经 5 日 EMA 平滑，避免单日毛刺。'),
  },
  return_stability: {
    title: t('波动稳定'),
    body: t('最近 20 日日收益率的标准差。数值越小，趋势运行越平稳；放大往往伴随行情性质切换。'),
  },
};

/* ---------------- K线结构分析面板 ---------------- */

const PRICE_ACTION_HINT: ScoreHint = {
  title: t('价格行为'),
  body: t('以结构状态定基准分（上升结构 82 / 区间震荡 50 / 下降结构 24），再叠加K线形态修正（吞没・锤子・射击之星各 ±6，合计上限 ±10）与陷阱修正（Spring +8 / Upthrust −8）。'),
};

export const STRUCTURE_HINTS: Record<string, ScoreHint> = {
  market_structure: {
    title: t('市场结构（HH/HL）'),
    body: t('用分形摆动点判断结构：比较最近两个摆动高点与两个摆动低点的抬升/压低组合，得到 HH+HL 上升、LH+LL 下降等六种状态。'),
    note: t('摆动点只取「已确认」的分形（右侧还需再走 3 根K线），因此不存在未来函数；最新 3 根K线不会产生新摆动点。'),
  },
  price_action_score: PRICE_ACTION_HINT,
  base_detection: {
    title: t('基底检测（枢轴聚类）'),
    body: t('在 10~80 日的七档窗口上寻找分形枢轴高点，按 max(1%×价格, 0.5×ATR) 的容差聚成阻力带，至少 2 次触碰才算有效基底；多窗口择优保留质量最高的一个。'),
    note: t('质量为七维加权：紧致度 25% / 持续时间 15% / 触碰次数 15% / 成交额收缩 15% / ATR收缩 10% / 支撑完整性 10% / 低点抬升 10%。检测只用突破日之前的K线。'),
  },
  vol_price: {
    title: t('量价一致（努力/结果）'),
    body: t('Wyckoff 式检验：努力 = 近10日成交额中位数 ÷ 60日基准；结果 = 同期涨跌幅 ÷ 波动基准。区间收缩时，量维持而价稳含上行偏向为「多头吸收」（突破质量 +12），量价同枯为「真空收缩」（−10、假突破风险 +12）。'),
    note: t('判定辅以 CLV（收盘在日内区间的位置）、涨跌日成交额比与 OBV 斜率；成交额缺失的交易日整行剔除，不当零处理。'),
  },
  spring: {
    title: t('Spring 假跌破回收'),
    body: t('近 8 根K线中，盘中跌破前一个已确认摆动低点但收盘收回其上——空头陷阱，偏多信号（价格行为 +8）。'),
  },
  upthrust: {
    title: t('Upthrust 假突破'),
    body: t('近 8 根K线中，盘中突破前一个已确认摆动高点但收盘跌回其下——多头陷阱，偏空信号（价格行为 −8，并计入追高风险）。'),
  },
  chart_overlays: {
    title: t('图上标记说明'),
    body: t('浅蓝色横带 = 检出基底的阻力带；绿色点线 = 失效位（基底支撑下沿再减 0.1×ATR）；▼ = 已确认摆动高点，▲ = 已确认摆动低点。'),
    note: t('仅复权视图绘制这些标记；未检出基底时只画摆动点。'),
  },
};

/* ---------------- 雷达评分维度（Lead 卡 & 结构面板共用） ---------------- */

export const RADAR_SCORE_HINTS: Record<string, ScoreHint> = {
  综合质量: {
    title: t('综合质量'),
    body: t('基底质量 40% + 突破确认 45% + 流动性 15% 加权，再叠加量价一致的 ±12 上限修正。'),
  },
  趋势质量: {
    title: t('趋势质量'),
    body: t('均线多头排列 22% + 站上75日线 12% + 63日涨幅映射 22% + 趋势持续度 14% + 价格结构 20% + RSI 映射 10%。'),
    note: t('缺失分量剔除并重新配权；置信度为可用权重占比。'),
  },
  基底质量: {
    title: t('基底质量'),
    body: t('检出完成基底时采用枢轴聚类七维评分；未检出时退回波动收缩与 20 日区间等代理指标，并下调置信度。'),
  },
  突破确认: {
    title: t('突破确认'),
    body: t('日内收盘位置 25% + 成交额相对 20 日中位数倍数 30% + 突破幅度（ATR 倍数）25% + 站稳天数 20%。'),
  },
  相对强度: {
    title: t('相对强度'),
    body: t('相对 TOPIX 的 63 日超额收益 60% + 相对所属东证 33 行业中位数超额收益 40%，映射 −5%～+25% 区间。'),
  },
  量能: {
    title: t('量能'),
    body: t('当日成交额 ÷ 前 20 日中位数（1～5 倍）60% + 近 5 日均额 ÷ 20 日均额（0.8～2.0 倍）40%。'),
  },
  流动性: {
    title: t('流动性'),
    body: t('20 日平均成交额按对数映射：约 5000 万日元为 0 分，100 亿日元为满分。'),
  },
  市场契合: {
    title: t('市场契合'),
    body: t('TOPIX 相对 50 日线（±20 分）与 200 日线（±15 分）的位置，加 20 日动量（±15 分），基准 50 分。'),
  },
  行业契合: {
    title: t('行业契合'),
    body: t('所属行业的 20 日中位涨幅在东证 33 行业中的百分位（0–100）。'),
  },
  追高风险: {
    title: t('追高风险'),
    body: t('取「距 25 日线的 ATR 倍数」与「5 日涨幅」较大者，叠加量价假突破风险与 Upthrust（+8）。'),
    note: t('超过 50 的部分按 ×0.25 从优先级中扣减。'),
  },
  拥挤度: {
    title: t('拥挤度'),
    body: t('信用倍率（融资余额 ÷ 融券余额）映射 2x～15x；倍率越高多头越拥挤。'),
    note: t('超过 50 的部分按 ×0.15 从优先级中扣减。'),
  },
  数据置信度: {
    title: t('数据置信度'),
    body: t('有效 K 线样本按 30～250 天线性映射；新股或长期停牌股得分较低。'),
  },
  优先级: {
    title: t('优先级'),
    body: t('综合质量 34% + 相对强度 22% + 市场契合 12% + 量能 12% + 行业契合 10% + 数据置信度 10%，扣减追高与拥挤度惩罚。'),
  },
  价格行为: PRICE_ACTION_HINT,
};

export function radarScoreHint(label: string): ScoreHint | undefined {
  return RADAR_SCORE_HINTS[label];
}

/* ---------------- 选股扫描（强度）页 ---------------- */

export const STRENGTH_HINTS: Record<string, ScoreHint> = {
  composite: {
    title: t('强度分'),
    body: t('排序分 = 内在强度 66% + 市场形态 8% + 偏好适配 26%（按置信度加权）。内在强度由短期 16% / 中期 24% / 长期 14% / 趋势 16% / 突破质量 15% / 价格行为 15% 六族合成。'),
    note: t('缺失维度按剩余权重重新配权；置信度为可用权重占比。'),
  },
  families: {
    title: t('六族分项'),
    body: t('短期(5/20日收益·量比·MA25距离·RSI)、中期(63日收益·TOPIX相对·均线排列·MACD·MA75距离)、长期(126/252日收益·MA200距离·52周高位)、趋势(动量·效率比·MA50斜率·稳定度)、突破质量(52周高位·20日收益·价格行为±量价修正)、价格行为(HH/HL结构评分)。'),
  },
  percentile: {
    title: t('横截面分位'),
    body: t('内在强度在全部已评分股票中的百分位（100 为最强）；同行业分位按东证 33 行业分组计算。'),
  },
  marketRegime: {
    title: t('市场形态'),
    body: t('六维合成：TOPIX 趋势 24%、动量 18%、广度（站上 200 日线占比）22%、量能 12%、风险偏好 12%、强弱价差（成长−主板 20 日中位收益差）12%。'),
  },
  news72h: {
    title: t('新闻 · 72H'),
    body: t('近 72 小时内已接入新闻源中关联该股的条数及最高重要度。'),
  },
  avgTurnover: {
    title: t('20日均额'),
    body: t('近 20 个交易日平均成交额，筛选条件中的成交额下限同此口径。'),
  },
  classification: {
    title: t('分类'),
    body: t('按强度分、均线排列、量能突破与风险扣分自动归档（质量趋势 / 放量突破 / 相对强势 / 回暖候选 / 高风险题材 / 观察）。'),
  },
  tierCounts: {
    title: t('强度分档'),
    body: t('全市场已评分股票的分档数量：S≥90 / A 80–89 / B 70–79 / C 60–69；<60 计入「全部」。'),
  },
  timeframe: {
    title: t('周期'),
    body: t('提高短期、中期或长期分项在内在强度中的权重；「全部周期」使用默认权重。'),
  },
  profile: {
    title: t('偏好'),
    body: t('稳健 / 均衡 / 进取调整波动率、流动性、回撤与单手金额的适配目标，占最终排序分 26%。'),
  },
  topN: {
    title: t('返回数量'),
    body: t('按当前条件过滤全市场后，返回排序最前的股票数量。'),
  },
};

export const FAMILY_HINTS: Record<string, ScoreHint> = {
  short: {
    title: t('短期'),
    body: t('5/20 日收益、量比、距 MA25 距离与 RSI14。约占内在强度 16%。'),
  },
  mid: {
    title: t('中期'),
    body: t('63 日收益、对 TOPIX 相对强度、均线排列、MACD 动向与距 MA75 距离。约占内在强度 24%。'),
  },
  long: {
    title: t('长期'),
    body: t('126/252 日收益、距 MA200 距离与 52 周高位位置。约占内在强度 14%。'),
  },
  trend: {
    title: t('趋势'),
    body: t('动量、Kaufman 效率比、MA50 斜率与波动稳定度。约占内在强度 16%。'),
  },
  breakout: {
    title: t('突破质量'),
    body: t('52 周高位位置、20 日收益，再叠加价格行为与量价一致的加减分。约占内在强度 15%。'),
  },
  price_action: PRICE_ACTION_HINT,
};

export const REGIME_DIM_HINTS: Record<string, ScoreHint> = {
  index_trend: {
    title: t('指数趋势'),
    body: t('TOPIX 相对 25/75/200 日均线的位置与斜率。'),
  },
  momentum: {
    title: t('市场动量'),
    body: t('TOPIX 近 20 日收益的强弱。'),
  },
  breadth: {
    title: t('市场广度'),
    body: t('全市场收于 200 日线上方的个股占比。'),
  },
  volume: {
    title: t('量能配合'),
    body: t('成交额高于自身 20 日均额的个股占比。'),
  },
  risk_appetite: {
    title: t('风险偏好'),
    body: t('全市场 20 日收益中位数的强弱。'),
  },
  risk_on_spread: {
    title: t('强弱价差'),
    body: t('成长市场与主板市场 20 日收益中位数之差。'),
  },
};

export const MARKET_HINTS: Record<string, ScoreHint> = {
  sectorMedian: {
    title: t('行业中位涨跌'),
    body: t('东证 33 行业成分股当日或近 20 日收益的中位数；底部细条表示行业内上涨股占比。'),
  },
};

export const NEWS_HINTS: Record<string, ScoreHint> = {
  importance: {
    title: t('新闻重要度'),
    body: t('按事件类别、关联个股与发布时效评分（0–100）：≥75 为高，≥55 为中，其余为普通。'),
  },
};

export const SHORT_HINTS = {
  crowding: {
    title: t('拥挤度'),
    body: t('按近期公开做空机构数与公开持仓比例分三档：机构 ≥ 4 家或持仓 ≥ 4% 为高；机构 ≥ 2 家或持仓 ≥ 2% 为中；其余有公开持仓者为低。'),
  },
  state: {
    title: t('20日动向'),
    body: t('按公开持仓净变动分类（步长 0.10 个百分点）：20 日净增达标且近 5 日未反向达标为「增加中」，净减达标为「减少中」；20 日与 5 日方向相反或仅 5 日达标为「方向反复」；均未达标为「持平」。'),
  },
  visibleShort: {
    title: t('公开持仓比例'),
    body: t('达到 0.5% 披露门槛且近 125 个交易日内有更新的机构持仓之和。'),
  },
  institutions: {
    title: t('近期机构数'),
    body: t('达到 0.5% 披露门槛且近 125 个交易日内有更新的机构数量；长期未更新的机构仍计入在册合计。'),
  },
  inScope: {
    title: t('在册合计'),
    body: t('最后报告仍在 0.5% 披露范围内的全部机构持仓之和，含长期未再更新报告的机构。'),
  },
  daysToCover: {
    title: t('回补天数'),
    body: t('公开持仓股数除以 20 日平均成交量。'),
  },
} satisfies Record<string, ScoreHint>;
