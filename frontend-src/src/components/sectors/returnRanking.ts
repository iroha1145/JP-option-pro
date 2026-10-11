import type { SectorStrength } from '@/api/types';

export type HeatMetric = 'r1' | 'r20';

/** 接口收益为比例（0.01 = 1%），排序和尺长始终保留这一单位。 */
export function metricValue(sector: SectorStrength, metric: HeatMetric): number | null {
  const value = metric === 'r1' ? sector.median_return_1d : sector.median_return_20d;
  return value != null && Number.isFinite(value) ? value : null;
}

/** 同值与缺值维持接口原顺序；缺值排最后，不把它当持平。 */
export function rankByReturn(sectors: SectorStrength[], metric: HeatMetric): SectorStrength[] {
  return sectors.map((sector, index) => ({ sector, index })).sort((a, b) => {
    const left = metricValue(a.sector, metric);
    const right = metricValue(b.sector, metric);
    if (left === null && right === null) return a.index - b.index;
    if (left === null) return 1;
    if (right === null) return -1;
    return right - left || a.index - b.index;
  }).map(({ sector }) => sector);
}

/** 全部行共用零轴和一把尺，涨跌相同幅度画成相同长度。 */
export function returnScale(sectors: SectorStrength[], metric: HeatMetric) {
  const values = sectors.flatMap((sector) => {
    const value = metricValue(sector, metric);
    return value === null ? [] : [value];
  });
  let low = Math.min(0, ...values);
  let high = Math.max(0, ...values);
  const span = metric === 'r1' ? 0.03 : 0.12;
  if (high === low) {
    low = -span / 2;
    high = span / 2;
  } else if (high - low < span) {
    const grow = span / (high - low);
    low *= grow;
    high *= grow;
  }
  return { axis: (-low / (high - low)) * 100, extent: high - low };
}
