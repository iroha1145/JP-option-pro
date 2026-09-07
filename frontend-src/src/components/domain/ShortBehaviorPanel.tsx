/* 个股页的「机构空卖行为」区块。
 *
 * 三层：行为指标 → 机构公开空头 → 事件时间线，最后是确定性解释卡片。
 *
 * 最重要的一条：跌破公开门槛之后不要把线画到 0。这里用「实线 = 精确公开
 * 报告状态 / 虚线 = 最后已知但当前不可见」来表示，并在每条上写明。 */

import { useEffect, useState } from 'react';
import { shortMonitorApi } from '@/api/modules';
import type { ShortMonitorDetail, ShortMonitorEvent, ShortMonitorHolder } from '@/api/types';
import { fmtDate, fmtDateShort, fmtPct, fmtPctLevel } from '@/lib/format';
import { explanationLine } from '@/lib/explainText';
import EmptyState from '@/components/shared/EmptyState';
import InfoHint from '@/components/shared/InfoHint';
import PointerTooltip from '@/components/shared/PointerTooltip';
import { SkeletonBlock } from '@/components/shared/Skeleton';
import { SHORT_HINTS, type ScoreHint } from '@/lib/indicatorHints';
import { t } from '@/i18n/core';

const EVENT_LABELS: Record<string, string> = {
  new: '新规进入',
  reentry: '重新进入',
  increased: '增仓',
  decreased: '减仓',
  below_threshold: '跌破门槛',
  closed: '解消',
};

/** 对股票的方向：红=买方有利（空头回补），绿=卖方有利（新空头进场）。 */
const EVENT_TONE: Record<string, string> = {
  new: 'text-down-600',
  reentry: 'text-down-600',
  increased: 'text-down-600',
  decreased: 'text-up-600',
  below_threshold: 'text-up-600',
  closed: 'text-up-600',
};

export default function ShortBehaviorPanel({ code }: { code: string }) {
  const [detail, setDetail] = useState<ShortMonitorDetail | null>(null);
  const [events, setEvents] = useState<ShortMonitorEvent[]>([]);
  const [eventTotal, setEventTotal] = useState(0);
  const [shown, setShown] = useState(20);
  const [missing, setMissing] = useState(false);

  useEffect(() => {
    let cancelled = false;
    // StockDetail は銘柄切替でアンマウントしない。前銘柄の 404 を残すと
    // 以降ずっと「暫無快照」になる。
    setMissing(false);
    setDetail(null);
    setEvents([]);
    setEventTotal(0);
    setShown(20);
    shortMonitorApi
      .stock(code)
      .then((data) => !cancelled && setDetail(data))
      .catch(() => !cancelled && setMissing(true));
    shortMonitorApi
      .events(code, { limit: 200 })
      .then((data) => {
        if (cancelled) return;
        setEvents(data.events);
        setEventTotal(data.total);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [code]);

  if (missing) {
    return (
      <EmptyState size="compact" image="/empty-chart.svg" title={t('该股票暂无机构空卖行为快照')} />
    );
  }
  if (!detail) {
    return (
      <div className="t-skel" data-state="loading" aria-busy="true">
        <div className="t-skel-skeleton is-pulsing space-y-2">
          <SkeletonBlock className="h-8 w-full" />
          <SkeletonBlock className="h-8 w-full" />
          <SkeletonBlock className="h-8 w-2/3" />
        </div>
      </div>
    );
  }

  const reporting = detail.holders.filter((h) => h.visibility_status === 'reporting');
  const below = detail.holders.filter((h) => h.visibility_status === 'below_public_threshold');
  const stale = detail.holders.filter((h) => h.stale_reporting);
  const unknown = detail.holders.filter((h) => h.visibility_status === 'unknown');

  return (
    <div className="space-y-3">
      <p className="rounded-md bg-paper-2 px-2.5 py-1.5 text-micro text-ink-500">
        {t('跌破公开披露门槛不代表实际空头仓位归零，后续精确仓位不可见。')}
      </p>

      {/* 下层：行为指标 */}
      <dl className="grid grid-cols-2 gap-1.5 sm:grid-cols-4">
        <Metric label="行为分" value={detail.behavior_score?.toFixed(0) ?? '—'} hint={SHORT_HINTS.behavior} />
        <Metric label="数据置信度" value={detail.data_confidence?.toFixed(2) ?? '—'} hint={SHORT_HINTS.confidence} />
        <Metric
          label="公开可见空头"
          value={fmtPctLevel(detail.visible_short_ratio)}
          hint={SHORT_HINTS.visibleShort}
        />
        <Metric
          label="在册合计（官方口径）"
          value={fmtPctLevel(detail.reported_in_scope_ratio)}
          hint={SHORT_HINTS.inScope}
        />
        <Metric
          label="公开可见回补天数"
          value={detail.visible_days_to_cover?.toFixed(2) ?? '—'}
          hint={SHORT_HINTS.daysToCover}
        />
        <Metric label="卖压吸收" value={detail.scores.absorption?.toFixed(0) ?? '—'} hint={SHORT_HINTS.absorption} />
        <Metric label="回补强度" value={detail.scores.covering?.toFixed(0) ?? '—'} hint={SHORT_HINTS.covering} />
        <Metric label="相对TOPIX（20日）" value={fmtPct(detail.rel_topix_20d)} />
        <Metric label="相对行业（20日）" value={fmtPct(detail.rel_sector_20d)} />
      </dl>

      {/* 中层：各机构最新公开状态 */}
      <div>
        <p className="mb-1 text-micro text-ink-400">
          {t('机构公开空头')}（{t('报告义务中')} {reporting.length - stale.length} · {t('跌破门槛')} {below.length}
          {stale.length > 0 ? ` · ${t('报告已停止')} ${stale.length}` : ''}
          {unknown.length > 0 ? ` · ${t('状态未知')} ${unknown.length}` : ''}）
        </p>
        {detail.holders.length === 0 ? (
          <EmptyState size="compact" image="/empty-chart.svg" title={t('当前没有公开披露的机构空头')} />
        ) : (
          <ul>
            {detail.holders.map((holder) => (
              <HolderRow key={holder.legal_id} holder={holder} />
            ))}
          </ul>
        )}
      </div>

      {/* 事件时间线 */}
      <div>
        <p className="mb-1 text-micro text-ink-400">
          {t('机构事件时间线')}（{eventTotal}）
        </p>
        {events.length === 0 ? (
          <EmptyState size="compact" image="/empty-chart.svg" title={t('暂无数据')} />
        ) : (
          <ul>
            {events.slice(0, shown).map((event) => (
              <EventRow key={event.event_id} event={event} />
            ))}
          </ul>
        )}
        {events.length > shown && (
          <button
            type="button"
            onClick={() => setShown((n) => n + 40)}
            className="mt-1 rounded-md bg-paper-2 px-2 py-1 text-micro text-ink-600 hover:bg-brand-50"
          >
            {t('展开更多')}
          </button>
        )}
      </div>

      {/* 解释卡片：确定性模板，不调用模型 */}
      <div className="rounded-md border border-line bg-paper-2 px-3 py-2">
        <p className="mb-1 text-micro text-ink-400">
          {t('当前判定')}：{t(detail.explanation.state_label)}
        </p>
        <ul className="space-y-0.5 text-body-s text-ink-700">
          {(detail.explanation.line_items ?? []).length > 0
            ? detail.explanation.line_items!.map((item, index) => (
                <li key={index}>{explanationLine(item)}</li>
              ))
            : detail.explanation.lines.map((line, index) => <li key={index}>{line}</li>)}
        </ul>
        {detail.explanation.caveat && (
          <p className="mt-1.5 text-micro text-ink-500">{t(detail.explanation.caveat)}</p>
        )}
      </div>
    </div>
  );
}

function Metric({ label, value, hint }: { label: string; value: string; hint?: ScoreHint }) {
  return (
    <div className="rounded-md bg-paper-2 px-2 py-1.5">
      <div className="flex items-center gap-0.5 text-micro text-ink-400">
        <span className="truncate">{t(label)}</span>
        {hint && <InfoHint hint={hint} size={11} side="bottom" />}
      </div>
      <div className="font-mono text-data-s tnum text-ink-900">{value}</div>
    </div>
  );
}

function HolderRow({ holder }: { holder: ShortMonitorHolder }) {
  // その仓位日時点で正確、の意味。今日の建玉が分かるという意味ではない。
  const known = holder.exact_at_position_date;
  return (
    <li className="flex min-h-[60px] items-center gap-3 px-1 py-[14px] transition-colors duration-fast hover:bg-paper-2/70">
      <div className="flex w-11 shrink-0 flex-col items-center self-stretch pt-0.5">
        <span className="font-mono text-[11px] leading-[14px] text-ink-400 tnum">
          {fmtDateShort(holder.last_position_date)}
        </span>
        <span className="mt-1.5 hidden w-[2px] flex-1 rounded-full bg-line sm:block" aria-hidden="true" />
      </div>
      <span className="min-w-0 flex-1 truncate text-body-s text-ink-700">{holder.name}</span>
      {holder.is_hedge_disclosed && (
        <span className="hidden shrink-0 whitespace-nowrap text-micro text-ink-400 sm:inline">{t('含对冲持仓')}</span>
      )}
      <span className={`shrink-0 whitespace-nowrap text-micro ${known ? 'text-ink-400' : 'text-up-600'}`}>
        {known
          ? t('报告义务中')
          : holder.stale_reporting
            ? t('报告已停止')
            : holder.visibility_status === 'unknown'
              ? t('状态未知')
              : t('跌破门槛')}
      </span>
      <span
        className={`shrink-0 font-mono text-caption tnum ${known ? 'text-ink-900' : 'text-ink-500 underline decoration-dotted underline-offset-2'}`}
      >
        {fmtPctLevel(holder.last_reported_ratio)}
      </span>
    </li>
  );
}

function EventRow({ event }: { event: ShortMonitorEvent }) {
  const tone = EVENT_TONE[event.event_type] ?? 'text-ink-400';
  return (
    <li className="px-1 transition-colors duration-fast hover:bg-paper-2/70">
      <div className="flex min-h-[60px] items-center gap-3 py-[14px]">
        <div className="flex w-11 shrink-0 flex-col items-center self-stretch pt-0.5">
          <span className="font-mono text-[11px] leading-[14px] text-ink-400 tnum">
            {fmtDateShort(event.position_date)}
          </span>
          <span className="mt-1.5 hidden w-[2px] flex-1 rounded-full bg-line sm:block" aria-hidden="true" />
        </div>
        <span className="min-w-0 flex-1 truncate text-body-s text-ink-700">{event.institution}</span>
        <span className={`shrink-0 whitespace-nowrap text-micro ${tone}`}>
          {t(EVENT_LABELS[event.event_type] ?? event.event_type)}
        </span>
        {event.correction_status === 'correction' && (
          <span className="shrink-0 whitespace-nowrap text-micro text-ink-400">{t('订正')}</span>
        )}
        <span className="shrink-0 font-mono text-caption tnum text-ink-900">{fmtPctLevel(event.short_ratio)}</span>
        <PointerTooltip
          passthrough
          label={t('仓位日期 → 公开日期')}
          width={180}
          contentClassName="p-2"
          content={<span className="text-micro text-ink-600">{t('仓位日期 → 公开日期')}</span>}
        >
          <span className="hidden shrink-0 whitespace-nowrap font-mono text-micro tnum text-ink-400 sm:inline">
            {fmtDate(event.position_date)} → {fmtDate(event.published_date)}
          </span>
        </PointerTooltip>
      </div>
      {event.event_type === 'below_threshold' && (
        <p className="pb-2 pl-14 text-micro text-ink-400">
          {t('该机构已降至公开披露门槛以下，实际剩余仓位未知。')}
        </p>
      )}
    </li>
  );
}
