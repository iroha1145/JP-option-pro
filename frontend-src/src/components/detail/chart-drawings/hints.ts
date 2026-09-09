import type { ScoreHint } from '@/lib/indicatorHints';
import { t } from '@/i18n/core';

export const LAYER_HINTS: Record<string, ScoreHint> = {
  ma20: { title: t('MA20'), body: t('20 日收盘均线，看短期方向。') },
  ma50: { title: t('MA50'), body: t('50 日收盘均线，看中期方向。') },
  ma200: { title: t('MA200'), body: t('200 日收盘均线，看长期方向；前 199 根没有读数，曲线从第 200 根才开始。') },
  swings: {
    title: t('摆动点'),
    body: t('标出已确认的高低点，并比较相邻同类点：高点抬升（HH）、低点抬升（HL）、高点降低（LH）、低点降低（LL）。'),
  },
  support_resistance: {
    title: t('支撑阻力'),
    body: t('由近期摆动点归纳出的水平价位带，价格多次在附近受阻或获支撑。'),
  },
  bases: {
    title: t('整理区'),
    body: t('标出横盘整理的阻力带、支撑带和形成时间。'),
  },
  gaps: {
    title: t('价格缺口（日线）'),
    body: t('相邻两根已收盘日线之间未交易的价格区间；被后续交易填掉的部分会缩小。'),
  },
  pivots: {
    title: t('pivot/invalidation'),
    body: t('突破参考价（pivot）是整理区的上沿；失效价（invalidation）表示该整理结构不再成立的价位。'),
  },
  auto_patterns: {
    title: t('自动趋势线/通道/三角形/楔形'),
    body: t('根据已确认的高低点绘制趋势线、通道、三角形和楔形；触碰次数和间隔达到要求后才显示。'),
    note: t('几何质量表示形状的吻合程度，不代表涨跌概率。'),
  },
  candles: {
    title: t('K线形态'),
    body: t('单根或两根 K 线的经典形态标记（如吞没、锤子），标在事件发生的那根上。'),
  },
  traps: {
    title: t('Spring/Upthrust'),
    body: t('假跌破收回（Spring）：跌破后迅速回到区间内。假突破回落（Upthrust）：突破后迅速跌回区间内。'),
  },
  breakouts: {
    title: t('突破触发/测试/失败'),
    body: t('显示突破后的进展：已触发、回踩测试或突破失败。'),
  },
  rsi: {
    title: t('RSI'),
    body: t('14 日相对强弱指数副图，0–100。前 14 根是预热期不出读数。'),
  },
  macd: {
    title: t('MACD'),
    body: t('显示 12/26 快慢均线之差、9 日信号线和柱状图；前 35 根用于计算初始值，暂不显示读数。'),
  },
  obv: {
    title: t('OBV'),
    body: t('能量潮：按收盘涨跌把成交量累加或累减，看量能是否与价格同向。'),
  },
  clv: {
    title: t('CLV'),
    body: t('收盘位置值：每根 K 线的收盘价落在当日高低区间的什么位置，衡量买卖压力。'),
  },
  range_persistence: {
    title: t('60日区间位置'),
    body: t('当前收盘价在最近 60 日高低区间中的相对位置，0 是区间底、1 是区间顶。'),
  },
  topix_rs: {
    title: t('TOPIX 相对强度'),
    body: t('比较该股与 TOPIX（指数代码 0000）的表现；缺少同日收盘价时不显示。'),
  },
};
