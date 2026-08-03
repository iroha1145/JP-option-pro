/* 机构空卖行为监控。
 *
 * 这一页展示的是「达到公开披露条件的机构空卖持仓」的变化，以及股价对这部分
 * 压力的反应。不是市场全部空头，也不是「空头增加就看跌」的机械指标。
 *
 * 三条不能违反的界面纪律：
 *   1. 顶部语义提示常驻，不随滚动消失；
 *   2. 跌破门槛的机构单独计数，绝不并入合计，也不画成 0；
 *   3. 门槛与权重未经历史验证时，页面自己说出来。 */

import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router';
import PageHeader from '@/components/shared/PageHeader';
import { InlineFallback } from '@/components/shared/Fallbacks';
import { shortMonitorApi } from '@/api/modules';
import type { ShortMonitorOverview, ShortMonitorRankings, ShortMonitorRow } from '@/api/types';
import { fmtDate, fmtPct } from '@/lib/format';
import { t } from '@/i18n/core';
import { cn } from '@/lib/utils';

const VIEWS: { key: string; label: string; hint: string }[] = [
  { key: 'low_conflict', label: '低位增空不跌', hint: '深度低位 + 公开空头增加或重新进入' },
  { key: 'absorption', label: '卖压吸收', hint: '空头压力较高，单位压力造成的价格损害较低' },
  { key: 'covering', label: '回补加速', hint: '多家机构减仓、公开空头快速下降' },
  { key: 'reentry', label: '机构重新进入', hint: '一度跌破门槛后再次进入公开范围' },
  { key: 'rotation', label: '机构轮换', hint: '一批退出、另一批进入。本身不是利好或利空' },
  { key: 'squeeze', label: '挤空确认', hint: '仅展示满足全部严格价格确认条件的股票' },
  { key: 'divergence_failed', label: '背离失效', hint: '空头继续增加且股价跌破长期支撑' },
  { key: 'all', label: '全部', hint: '当日全部覆盖股票' },
];

const STATE_LABELS: Record<string, string> = {
  normal_shorting: '正常做空',
  low_conflict: '低位冲突',
  absorption: '卖压吸收',
  covering_start: '回补启动',
  squeeze_confirmed: '挤空确认',
  divergence_failed: '背离失效',
  no_signal: '无动向',
};

const FLAG_LABELS: Record<string, string> = {
  new_entry: '新规进入',
  reentry: '重新进入',
  rotation: '机构轮换',
  concentrated: '空头集中',
  multi_reduction: '多机构减仓',
  below_threshold: '跌破门槛',
  not_visible: '数据不可见',
  crowded_margin: '信用买入拥挤',
  regulated: '信用规制',
  earnings_near: '财报临近',
  news_catalyst: '新闻催化',
  thin_liquidity: '低流动性',
  stale_data: '数据过期',
  hedge_disclosed: '含对冲持仓',
  single_institution: '仅1家可见',
};

export default function ShortMonitor() {
  const [overview, setOverview] = useState<ShortMonitorOverview | null>(null);
  const [rankings, setRankings] = useState<ShortMonitorRankings | null>(null);
  const [view, setView] = useState('absorption');
  const [minConfidence, setMinConfidence] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    shortMonitorApi
      .overview()
      .then((data) => !cancelled && setOverview(data))
      .catch((e) => !cancelled && setError(String(e)));
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    shortMonitorApi
      .rankings({ view, limit: 60, min_confidence: minConfidence || undefined })
      .then((data) => {
        if (cancelled) return;
        setRankings(data);
        setError(null);
      })
      .catch((e) => !cancelled && setError(String(e)))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [view, minConfidence]);

  const activeView = useMemo(() => VIEWS.find((v) => v.key === view) ?? VIEWS[0], [view]);
  const unvalidated = overview?.validated && !overview.validated.score;

  return (
    <div className="space-y-4">
      <PageHeader
        section={t('研究')}
        eyebrow="SHORT MONITOR"
        title={t('机构空卖行为监控')}
        description={t('公开披露的机构空卖持仓发生了什么变化，股价对这部分压力作出了什么反应')}
      />

      {/* 语义提示常驻。这一句不能因为版面紧张就删掉。 */}
      <p className="rounded-md border border-line bg-paper-2 px-3 py-2 text-caption text-ink-600">
        {t('本页面展示达到公开披露条件的机构空卖持仓，不代表市场全部空头仓位。跌破公开门槛不代表仓位归零。')}
      </p>

      {overview && <OverviewStrip overview={overview} />}

      {unvalidated && (
        <p className="rounded-md border border-warn-200 bg-warn-50 px-3 py-2 text-caption text-warn-700">
          {t('当前门槛与权重为初始参数，尚未通过历史验证，仅作研究排序使用。')}
        </p>
      )}

      <div className="flex flex-wrap items-center gap-1.5">
        {VIEWS.map((item) => (
          <button
            key={item.key}
            type="button"
            onClick={() => setView(item.key)}
            title={t(item.hint)}
            className={cn(
              'rounded-md px-2.5 py-1 text-body-s transition-colors',
              item.key === view
                ? 'bg-brand-600 font-medium text-white'
                : 'bg-paper-2 text-ink-600 hover:bg-brand-50 hover:text-ink-900',
            )}
          >
            {t(item.label)}
          </button>
        ))}
        <label className="ml-auto flex items-center gap-1.5 text-micro text-ink-500">
          {t('最低数据置信度')}
          <select
            value={minConfidence}
            onChange={(e) => setMinConfidence(Number(e.target.value))}
            className="rounded-md border border-line bg-paper px-1.5 py-1 text-body-s text-ink-900"
          >
            <option value={0}>{t('不限')}</option>
            <option value={0.35}>0.35</option>
            <option value={0.6}>0.60</option>
            <option value={0.8}>0.80</option>
          </select>
        </label>
      </div>

      <p className="text-micro text-ink-400">{t(activeView.hint)}</p>

      {error && (
        <p className="rounded-md border border-line bg-paper-2 px-3 py-2 text-caption text-ink-600">
          {t('读取失败')}: {error}
        </p>
      )}
      {loading && !rankings && <InlineFallback />}
      {rankings && <RankingTable rankings={rankings} />}
    </div>
  );
}

function OverviewStrip({ overview }: { overview: ShortMonitorOverview }) {
  const states = overview.states || {};
  const coverage = overview.coverage;
  const cells: { label: string; value: string }[] = [
    { label: '最近数据日期', value: overview.as_of_date ? fmtDate(overview.as_of_date) : '—' },
    { label: '覆盖股票', value: coverage ? String(coverage.covered) : '—' },
    { label: '有公开机构空头', value: coverage ? String(coverage.with_visible_short) : '—' },
    { label: '卖压吸收', value: String(states.absorption ?? 0) },
    { label: '回补启动', value: String(states.covering_start ?? 0) },
    { label: '挤空确认', value: String(states.squeeze_confirmed ?? 0) },
    { label: '背离失效', value: String(states.divergence_failed ?? 0) },
    { label: '置信度偏低', value: coverage ? String(coverage.low_confidence) : '—' },
  ];
  return (
    <dl className="grid grid-cols-2 gap-1.5 sm:grid-cols-4 xl:grid-cols-8">
      {cells.map((cell) => (
        <div key={cell.label} className="rounded-md bg-paper-2 px-2 py-1.5">
          <dt className="truncate text-micro text-ink-400">{t(cell.label)}</dt>
          <dd className="font-mono text-data-s tnum text-ink-900">{cell.value}</dd>
        </div>
      ))}
    </dl>
  );
}

function RankingTable({ rankings }: { rankings: ShortMonitorRankings }) {
  if (rankings.rows.length === 0) {
    return <p className="text-body-s text-ink-400">{t('该视图当前没有符合条件的股票')}</p>;
  }
  return (
    <>
      {/* 桌面表格 */}
      <div className="hidden overflow-x-auto md:block">
        <table className="w-full min-w-[1000px] text-body-s">
          <thead>
            <tr className="border-b border-line text-left text-micro text-ink-400">
              <th className="py-1.5 pr-2 font-normal">{t('代码')}</th>
              <th className="py-1.5 pr-2 font-normal">{t('名称')}</th>
              <th className="py-1.5 pr-2 font-normal">{t('市场')}</th>
              <th className="py-1.5 pr-2 font-normal">{t('状态')}</th>
              <th className="py-1.5 pr-2 text-right font-normal">{t('行为分')}</th>
              <th className="py-1.5 pr-2 text-right font-normal">{t('置信度')}</th>
              <th className="py-1.5 pr-2 text-right font-normal">{t('52周回撤')}</th>
              <th className="py-1.5 pr-2 text-right font-normal">{t('公开可见空头')}</th>
              <th className="py-1.5 pr-2 text-right font-normal">{t('5日变化')}</th>
              <th className="py-1.5 pr-2 text-right font-normal">{t('变化/ADV20')}</th>
              <th className="py-1.5 pr-2 text-right font-normal">{t('机构数')}</th>
              <th className="py-1.5 pr-2 text-right font-normal">{t('相对TOPIX')}</th>
              <th className="py-1.5 pr-2 text-right font-normal">{t('相对行业')}</th>
              <th className="py-1.5 font-normal">{t('标签')}</th>
            </tr>
          </thead>
          <tbody>
            {rankings.rows.map((row) => (
              <tr key={row.canonical_code} className="border-b border-line/60 hover:bg-paper-2">
                <td className="py-1.5 pr-2 font-mono tnum">
                  <Link to={`/stock/${row.canonical_code}`} className="text-brand-700 hover:underline">
                    {row.display_code}
                  </Link>
                </td>
                <td className="max-w-[180px] truncate py-1.5 pr-2 text-ink-700">{row.name ?? '—'}</td>
                <td className="py-1.5 pr-2 text-micro text-ink-500">{row.market_name ?? '—'}</td>
                <td className="py-1.5 pr-2">
                  <StateChipInline state={row.primary_state} />
                </td>
                <td className="py-1.5 pr-2 text-right font-mono tnum text-ink-900">
                  {row.behavior_score != null ? row.behavior_score.toFixed(0) : '—'}
                </td>
                <td className="py-1.5 pr-2 text-right font-mono text-micro tnum text-ink-500">
                  {row.data_confidence != null ? row.data_confidence.toFixed(2) : '—'}
                </td>
                <td className="py-1.5 pr-2 text-right font-mono tnum">{fmtPct(row.drawdown_52w)}</td>
                <td className="py-1.5 pr-2 text-right font-mono tnum">{fmtPct(row.visible_short_ratio)}</td>
                <td className="py-1.5 pr-2 text-right font-mono tnum">
                  <Signed value={row.ratio_change_5d} />
                </td>
                <td className="py-1.5 pr-2 text-right font-mono tnum">
                  {row.pressure_adv20_20d != null ? row.pressure_adv20_20d.toFixed(2) : '—'}
                </td>
                <td className="py-1.5 pr-2 text-right font-mono tnum">
                  {row.visible_institution_count}
                  {row.below_threshold_count > 0 && (
                    <span className="ml-1 text-micro text-ink-400">+{row.below_threshold_count}?</span>
                  )}
                </td>
                <td className="py-1.5 pr-2 text-right font-mono tnum">
                  <Signed value={row.rel_topix_20d} />
                </td>
                <td className="py-1.5 pr-2 text-right font-mono tnum">
                  <Signed value={row.rel_sector_20d} />
                </td>
                <td className="py-1.5">
                  <Flags flags={row.flags} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="mt-1 text-micro text-ink-400">
          {t('机构数后的 +N? 表示已跌破公开门槛、实际持仓不再披露的机构家数（不计入合计）')}
        </p>
      </div>

      {/* 移动卡片 */}
      <ul className="space-y-2 md:hidden">
        {rankings.rows.map((row) => (
          <li key={row.canonical_code} className="rounded-md border border-line bg-paper p-2.5">
            <MobileCard row={row} />
          </li>
        ))}
      </ul>
    </>
  );
}

function MobileCard({ row }: { row: ShortMonitorRow }) {
  return (
    <div className="space-y-1.5">
      <div className="flex items-baseline gap-2">
        <Link to={`/stock/${row.canonical_code}`} className="font-mono tnum text-brand-700">
          {row.display_code}
        </Link>
        <span className="min-w-0 flex-1 truncate text-body-s text-ink-700">{row.name ?? '—'}</span>
        <StateChipInline state={row.primary_state} />
      </div>
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 font-mono text-micro tnum text-ink-500">
        <span>
          {t('行为分')} <b className="text-ink-900">{row.behavior_score?.toFixed(0) ?? '—'}</b>
        </span>
        <span>
          {t('置信度')} {row.data_confidence?.toFixed(2) ?? '—'}
        </span>
        <span>
          {t('公开可见空头')} {fmtPct(row.visible_short_ratio)}
        </span>
        <span>
          {t('机构数')} {row.visible_institution_count}
          {row.below_threshold_count > 0 ? ` +${row.below_threshold_count}?` : ''}
        </span>
        <span>
          {t('52周回撤')} {fmtPct(row.drawdown_52w)}
        </span>
        <span>
          {t('相对TOPIX')} <Signed value={row.rel_topix_20d} />
        </span>
      </div>
      <Flags flags={row.flags} />
    </div>
  );
}

function StateChipInline({ state }: { state: string }) {
  return (
    <span className="shrink-0 whitespace-nowrap rounded-sm bg-paper-2 px-1.5 py-0.5 text-micro text-ink-600">
      {t(STATE_LABELS[state] ?? state)}
    </span>
  );
}

function Flags({ flags }: { flags: string[] }) {
  if (!flags?.length) return <span className="text-micro text-ink-300">—</span>;
  return (
    <span className="flex flex-wrap gap-1">
      {flags.map((flag) => (
        <span key={flag} className="rounded-sm bg-paper-2 px-1 py-0.5 text-micro text-ink-500">
          {t(FLAG_LABELS[flag] ?? flag)}
        </span>
      ))}
    </span>
  );
}

/** 红涨绿跌。空头比例本身的增减按数值符号着色。 */
function Signed({ value }: { value: number | null }) {
  if (value == null) return <span className="text-ink-400">—</span>;
  const tone = value > 0 ? 'text-up-600' : value < 0 ? 'text-down-600' : 'text-ink-400';
  const sign = value > 0 ? '+' : value < 0 ? '−' : '±';
  return (
    <span className={tone}>
      {sign}
      {(Math.abs(value) * 100).toFixed(2)}%
    </span>
  );
}
