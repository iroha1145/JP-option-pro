/**
 * 雷达其余信号小卡网格（结构对齐美国站 breakouts/SignalCards）：
 * 代码方块 + 代码 / 公司名 / 行业 · 形态与状态徽章 · 大号价格与距枢轴 · 价位刻度
 * · 同股其他信号徽章 · 分项评分折叠 · 底部评分条与日期。
 * 同一只股票的多条信号已由 groupSignalsByStock 合并成一张卡；网格分批挂载，首屏 12 张。
 */
import { Link } from 'react-router';
import { motion } from 'framer-motion';
import TickPrice from '@/components/shared/TickPrice';
import SoftBadge from '@/components/shared/SoftBadge';
import StrengthBar from '@/components/shared/StrengthBar';
import CodeMark from '@/components/shared/CodeMark';
import Icon from '@/components/icons';
import { RADAR_STATE_LABELS, SIGNAL_LABELS } from '@/components/domain';
import { useProgressiveList } from '@/hooks/useProgressiveList';
import { DUR_SECTION, EASE_PAPER } from '@/lib/motion';
import { fmtDate, fmtPct, fmtPrice, fmtYenCompact } from '@/lib/format';
import { cn } from '@/lib/utils';
import { t } from '@/i18n/core';
import type { IntradayOverlayRow, RadarEvent } from '@/api/types';
import PriceScale from './PriceScale';
import ScoreBarsMini from './ScoreBarsMini';
import { SiblingSignals } from './LeadBigCard';
import { radarStateChipClass } from './stateTone';
import type { SignalGroup } from './groupSignals';

const PAGE = 12;
const fin = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);

function SignalCard({
  group,
  index,
  live,
  flash,
  onPromote,
}: {
  group: SignalGroup<RadarEvent>;
  index: number;
  live?: IntradayOverlayRow;
  flash?: 'up' | 'down';
  onPromote: (eventId: string) => void;
}) {
  const event = group.primary;
  const structure = event.structure ?? null;
  const current = live?.live_price ?? (event.snapshot.close as number | null);
  const turnoverRatio = event.snapshot.turnover_ratio;
  const onSelect = () => onPromote(event.event_id);

  return (
    <motion.article
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: DUR_SECTION, ease: EASE_PAPER, delay: Math.min((index % PAGE) * 0.045, 0.5) }}
      className="relative"
    >
      {/* 整卡点击与代码链接是兄弟，避免按钮里再嵌链接。 */}
      <button
        type="button"
        onClick={onSelect}
        aria-label={t('{code} 雷达信号卡', { code: event.display_code })}
        className="absolute inset-0 z-0 rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-600"
      />
      <div
        className="radar-signal-card card-surface card-lift relative z-10 flex h-full cursor-pointer flex-col"
        onClick={(click) => {
          const target = click.target as Element;
          if (target.closest('button, a, summary, [role="button"]')) return;
          if (window.getSelection()?.toString()) return;
          onSelect();
        }}
      >
        {/* 顶行：代码方块 + 代码 / 公司名 / 行业 + 发现日 */}
        <div className="flex items-center gap-2.5">
          <CodeMark code={event.display_code} size={32} />
          <div className="min-w-0 flex-1">
            <Link
              to={`/stock/${event.display_code}`}
              className="tnum text-body-s font-medium text-ink-800 underline-offset-2 transition-colors duration-fast hover:text-brand-600 hover:underline"
            >
              {event.display_code}
            </Link>
            <div className="mt-0.5 flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
              <p className="min-w-0 truncate text-micro text-ink-400">{event.name_ja ?? '—'}</p>
              {event.sector33_name && <SoftBadge tone="neutral">{t(event.sector33_name)}</SoftBadge>}
            </div>
          </div>
          <span className="shrink-0 tnum text-micro text-ink-400">{fmtDate(event.discovered_date)}</span>
        </div>

        {/* 徽章行：形态 + 状态 + 盘中站上枢轴 · 右侧量比 */}
        <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
          <span className="radar-chip radar-chip-brand">{t(SIGNAL_LABELS[event.signal_type] ?? event.signal_type)}</span>
          <span className={cn('radar-chip', radarStateChipClass(event.state))}>
            {t(RADAR_STATE_LABELS[event.state] ?? event.state)}
          </span>
          {structure?.setup_label && <SoftBadge tone="ai">{t(structure.setup_label)}</SoftBadge>}
          {live?.above_pivot && (
            <SoftBadge tone="warn">
              <span className="inline-block size-1.5 rounded-full bg-warn-600" aria-hidden />
              {t('盘中站上枢轴')}
            </SoftBadge>
          )}
          <span className="radar-chip radar-chip-neutral ml-auto tnum">
            {t('量比')} {fin(turnoverRatio) ? `${turnoverRatio.toFixed(1)}×` : '—'}
          </span>
        </div>

        {/* 价格行：现价（盘中价或收盘）· 距枢轴 */}
        <div className="radar-quote-row mt-3 flex items-end justify-between gap-2">
          <TickPrice flash={flash} className="text-data-l text-ink-900">
            {fmtPrice(current)}
          </TickPrice>
          <span className="flex shrink-0 items-baseline gap-1.5 text-micro text-ink-400">
            {live ? t('盘中价') : t('收盘')}
            {live && fin(live.pivot_distance_pct) && (
              <span className={cn('tnum', live.pivot_distance_pct >= 0 ? 'text-up-700' : 'text-down-700')}>
                {t('距枢轴')} {fmtPct(live.pivot_distance_pct, 1)}
              </span>
            )}
          </span>
        </div>

        <PriceScale
          className="mt-2"
          invalidation={structure?.base?.invalidation_price}
          trigger={event.trigger_price ?? event.pivot_price}
          current={current}
          flash={flash}
        />

        {group.others.length > 0 && (
          <SiblingSignals siblings={group.others} onPromote={onPromote} className="mt-3" />
        )}

        <details className="radar-disclosure mt-3">
          <summary>
            <span>{t('分项评分')}</span>
            <Icon name="chevron-down" size={14} className="radar-disclosure-arrow" />
          </summary>
          <ScoreBarsMini event={event} className="pb-3 pt-1" />
        </details>

        {/* 底行：告警优先级条 · 成交额 */}
        <div className="radar-card-footer mt-auto flex items-center justify-between gap-3 pt-3">
          <StrengthBar score={fin(event.alert_priority) ? Math.round(event.alert_priority) : null} width={64} />
          <span className="tnum text-micro text-ink-500">
            {t('成交额')} {fmtYenCompact(event.snapshot.turnover_today as number | null)}
          </span>
        </div>
      </div>
    </motion.article>
  );
}

/** 父组件以筛选条件作 key 挂载：条件变化时批次从首屏 12 张重新开始。 */
export default function SignalCards({
  groups,
  overlay,
  flashes,
  onPromote,
}: {
  groups: SignalGroup<RadarEvent>[];
  overlay: Record<string, IntradayOverlayRow>;
  flashes: Record<string, 'up' | 'down'>;
  onPromote: (eventId: string) => void;
}) {
  const list = useProgressiveList(groups, { initial: PAGE, step: PAGE });
  if (groups.length === 0) return null;
  return (
    <div>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
        {list.visible.map((group, index) => (
          <SignalCard
            key={group.key}
            group={group}
            index={index}
            live={overlay[group.primary.event_id]}
            flash={flashes[group.primary.event_id]}
            onPromote={onPromote}
          />
        ))}
      </div>
      <div className="radar-load-more mt-5">
        {list.hasMore ? (
          <button type="button" onClick={list.loadMore} className="control-button mobile-control-target">
            {t('加载更多')}
            <span className="tnum text-micro text-ink-400">{t('还有 {n} 只股票', { n: list.remaining })}</span>
          </button>
        ) : (
          groups.length > PAGE && (
            <p className="tnum text-micro text-ink-400">{t('已显示全部 {n} 只股票', { n: groups.length })}</p>
          )
        )}
      </div>
    </div>
  );
}
