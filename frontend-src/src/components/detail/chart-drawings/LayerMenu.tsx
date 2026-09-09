/**
 * 算法与图层：居中小窗。面积模式下副图/均线开关禁用，不只靠文案。
 */
import { useEffect, useId, useRef, type CSSProperties, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { useFocusTrap } from '@/hooks/useFocusTrap';
import { useBodyScrollLock } from '@/hooks/useBodyScrollLock';
import { isTopFocusScope } from '@/lib/focusScope';
import { cn } from '@/lib/utils';
import Icon from '@/components/icons';
import InfoHint from '@/components/shared/InfoHint';
import FilterButton from '@/components/shared/FilterButton';
import SelectionViewport from '@/components/shared/SelectionViewport';
import Switch from '@/components/shared/Switch';
import {
  overlayClassName,
  overlayVisible,
  readRootDurationMs,
  useOverlayPhase,
} from '@/lib/transitions';
import { LAYER_HINTS } from './hints';
import type { ScoreHint } from '@/lib/indicatorHints';
import { t } from '@/i18n/core';
import { GROUPS, LAYERS, PRESETS, type PresetId } from './analysis/registry.ts';
import { DEFAULT_LAYER_SETTINGS, settingsFromPreset, toggleLayer, type LayerSettings } from './analysis/settings.ts';

const PRESET_ORDER: Exclude<PresetId, 'custom'>[] = [
  'minimal',
  'structure',
  'breakout',
  'momentum',
  'volume',
  'all',
];

const FOCUS_RING = 'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-500/30';

function layerInputEnabled(
  layer: { group: string; kind: string },
  mode: 'candle' | 'area',
): { enabled: boolean; reason: string | null } {
  if (mode === 'area' && (layer.group === 'pane' || layer.kind === 'ma')) {
    return { enabled: false, reason: 'area_no_panes_or_ma' };
  }
  return { enabled: true, reason: null };
}

function PopValue({ text }: { text: string }) {
  return (
    <span className="t-digit-group">
      {[...text].map((ch, i) => (
        <span key={`${ch}-${i}`} className="t-digit">{ch}</span>
      ))}
    </span>
  );
}

function ValueBadge({ text, className }: { text: string; className?: string }) {
  return (
    <span
      className={cn(
        'inline-flex h-6 items-center justify-center rounded-sm bg-paper-2 font-mono leading-none text-ink-700 tnum',
        className,
      )}
    >
      <PopValue text={text} />
    </span>
  );
}

function SliderRow({
  label,
  value,
  step,
  onApply,
}: {
  label: string;
  value: number;
  step: number;
  onApply: (next: number) => void;
}) {
  return (
    <div className="flex h-8 items-center gap-2.5 rounded-md px-1.5 transition-colors duration-fast hover:bg-paper-2/70">
      <span className="min-w-0 flex-1 truncate">{label}</span>
      <input
        type="range"
        min={0}
        max={100}
        step={step}
        aria-label={label}
        value={value}
        onChange={(event) => onApply(Number(event.target.value))}
        className="ft-range w-28 shrink-0 cursor-pointer"
        style={{ '--fill': `${value}%` } as CSSProperties}
      />
      <ValueBadge text={`${value}%`} className="w-12 shrink-0" />
    </div>
  );
}

const MAX_PATTERNS = 24;

const STEPPER_BUTTON = cn(
  'inline-flex size-6 shrink-0 items-center justify-center rounded-md border border-line bg-card leading-none text-ink-500 shadow-btn transition-[transform,color,background-color] duration-fast hover:bg-paper-2 hover:text-ink-700 active:scale-95 disabled:cursor-not-allowed disabled:opacity-40',
  FOCUS_RING,
);

function StepperRow({
  label,
  value,
  onChange,
}: {
  label: string;
  value: number;
  onChange: (next: number) => void;
}) {
  return (
    <div className="flex h-8 items-center justify-between gap-2 rounded-md px-1.5 transition-colors duration-fast hover:bg-paper-2/70">
      <span className="min-w-0 truncate">{label}</span>
      <span className="flex items-center gap-1">
        <button
          type="button"
          aria-label={t('减少')}
          disabled={value <= 0}
          onClick={() => onChange(Math.max(0, value - 1))}
          className={STEPPER_BUTTON}
        >
          −
        </button>
        <ValueBadge text={String(value)} className="w-9 shrink-0" />
        <button
          type="button"
          aria-label={t('增加')}
          disabled={value >= MAX_PATTERNS}
          onClick={() => onChange(Math.min(MAX_PATTERNS, value + 1))}
          className={STEPPER_BUTTON}
        >
          +
        </button>
      </span>
    </div>
  );
}

function LayerRow({
  label,
  checked,
  disabled,
  reason,
  hint,
  onToggle,
}: {
  label: string;
  checked: boolean;
  disabled?: boolean;
  reason?: string | null;
  hint?: ScoreHint;
  onToggle: () => void;
}) {
  return (
    <div
      title={reason ?? undefined}
      onClick={() => {
        if (!disabled) onToggle();
      }}
      className={cn(
        'flex min-h-8 items-center justify-between gap-2 rounded-md px-1.5 transition-colors duration-fast',
        disabled ? 'cursor-not-allowed text-ink-400' : 'cursor-pointer hover:bg-paper-2/70',
      )}
    >
      <span className="flex min-w-0 items-center gap-1.5">
        <span className="truncate">{label}</span>
        {hint && <InfoHint hint={hint} side="bottom" align="start" size={12} className="shrink-0" />}
      </span>
      <Switch checked={checked} disabled={disabled} label={label} onToggle={onToggle} />
    </div>
  );
}

function Card({ title, meta, children, className }: { title: string; meta?: string; children: ReactNode; className?: string }) {
  return (
    <section className={cn('rounded-lg border border-line bg-card p-2 shadow-card', className)}>
      <div className="mb-1 flex h-6 items-center justify-between px-1.5 pt-0.5">
        <h3 className="font-medium leading-none text-ink-600">{title}</h3>
        {meta && <span className="font-mono text-micro leading-none text-ink-300 tnum">{meta}</span>}
      </div>
      {children}
    </section>
  );
}

export default function LayerMenu({
  open,
  onClose,
  settings,
  onChange,
  mode = 'candle',
}: {
  open: boolean;
  onClose: () => void;
  settings: LayerSettings;
  onChange: (next: LayerSettings) => void;
  mode?: 'candle' | 'area';
}) {
  const patch = (next: Partial<LayerSettings>) => onChange({ ...settings, preset: 'custom', ...next });
  const panelRef = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const descId = useId();
  const closeMs = readRootDurationMs('--modal-close-dur', 150);
  const phase = useOverlayPhase(open, closeMs);
  const mounted = overlayVisible(open, phase);
  useFocusTrap(panelRef, open);
  useBodyScrollLock(mounted);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape' || e.defaultPrevented || e.isComposing || e.keyCode === 229 || !isTopFocusScope(panelRef.current)) return;
      e.preventDefault();
      e.stopImmediatePropagation();
      onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('keydown', onKey);
    };
  }, [open, onClose]);

  if (!mounted) return null;

  const [primaryGroup, ...secondaryGroups] = GROUPS;
  const groupCard = (group: (typeof GROUPS)[number]) => {
    const rows = LAYERS.filter((layer) => layer.group === group.id);
    const onCount = rows.filter((layer) => settings.enabled.includes(layer.id)).length;
    return (
      <Card key={group.id} title={group.label} meta={`${onCount}/${rows.length}`}>
        <ul className="flex flex-col">
          {rows.map((layer) => {
            const gate = layerInputEnabled(layer, mode);
            return (
              <li key={layer.id}>
                <LayerRow
                  label={layer.label}
                  checked={settings.enabled.includes(layer.id)}
                  disabled={!gate.enabled}
                  reason={gate.reason === 'area_no_panes_or_ma' ? t('面积图不支持副图与均线叠加') : null}
                  hint={LAYER_HINTS[layer.id]}
                  onToggle={() => onChange(toggleLayer(settings, layer.id))}
                />
              </li>
            );
          })}
        </ul>
      </Card>
    );
  };

  return createPortal(
    <>
      <div
        className={cn('t-backdrop fixed inset-0 z-[85] bg-[rgba(13,22,38,.34)] backdrop-blur-[2px]', phase === 'open' && 'is-open')}
        onClick={onClose}
        data-focus-backdrop={titleId}
        aria-hidden="true"
      />
      <div className="pointer-events-none fixed left-1/2 top-[max(8px,env(safe-area-inset-top))] z-[86] w-[680px] max-w-[calc(100vw-12px)] -translate-x-1/2 sm:top-1/2 sm:-translate-y-1/2">
        <div
          ref={panelRef}
          role="dialog"
          aria-modal="true"
          data-focus-overlay={titleId}
          aria-labelledby={titleId}
          aria-describedby={descId}
          className={cn(
            't-modal pointer-events-auto flex max-h-[min(88dvh,calc(100dvh-16px-env(safe-area-inset-bottom)))] flex-col overflow-hidden rounded-xl border border-line bg-paper-2 shadow-sh-3',
            overlayClassName(phase),
          )}
        >
          <div className="flex shrink-0 items-center justify-between gap-3 border-b border-line bg-card px-4 py-3 sm:px-5">
            <div className="min-w-0">
              <h2 id={titleId} className="truncate text-body font-medium leading-tight text-ink-900">{t('算法与图层')}</h2>
              <p id={descId} className="mt-0.5 truncate text-micro text-ink-400">{t('选择预设，或逐层微调算法与图层。')}</p>
            </div>
            <div className="flex shrink-0 items-center gap-1.5">
              <button
                type="button"
                onClick={() => onChange({ ...DEFAULT_LAYER_SETTINGS, enabled: [...DEFAULT_LAYER_SETTINGS.enabled] })}
                className={cn(
                  'inline-flex h-8 items-center rounded-md border border-line bg-card px-2.5 text-micro leading-none text-ink-500 shadow-btn transition-[transform,color,background-color] duration-fast hover:bg-paper-2 hover:text-ink-700 active:scale-95',
                  FOCUS_RING,
                )}
              >
                {t('恢复默认')}
              </button>
              <button
                type="button"
                onClick={onClose}
                className={cn(
                  'inline-flex size-8 items-center justify-center rounded-md text-ink-400 transition-[transform,color,background-color] duration-fast hover:bg-paper-2 hover:text-ink-600 active:scale-95',
                  FOCUS_RING,
                )}
                aria-label={t('关闭')}
              >
                <Icon name="x" size={16} />
              </button>
            </div>
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain p-4 text-micro">
            <SelectionViewport>
              <div className="mobile-selection-rail flex flex-wrap items-center gap-1.5">
                {PRESET_ORDER.map((id) => (
                  <FilterButton
                    key={id}
                    active={settings.preset === id}
                    aria-label={PRESETS[id].label}
                    onClick={() => onChange(settingsFromPreset(id))}
                  >
                    {PRESETS[id].label}
                  </FilterButton>
                ))}
              </div>
            </SelectionViewport>

            <div className="mt-3 flex flex-col gap-3 sm:flex-row sm:items-start">
              <div className="flex min-w-0 flex-1 flex-col gap-3">{groupCard(primaryGroup)}</div>
              <div className="flex min-w-0 flex-1 flex-col gap-3">{secondaryGroups.map(groupCard)}</div>
            </div>

            <Card title={t('高级')} className="mt-3">
              <SliderRow
                label={t('最低几何质量')}
                value={Math.round(settings.minShapeQuality * 100)}
                step={5}
                onApply={(next) => patch({ minShapeQuality: next / 100 })}
              />
              <SliderRow
                label={t('标签密度')}
                value={Math.round(settings.labelDensity * 100)}
                step={10}
                onApply={(next) => patch({ labelDensity: next / 100 })}
              />
              <StepperRow
                label={t('最大形态数')}
                value={settings.maxPatterns}
                onChange={(next) => patch({ maxPatterns: next })}
              />
              <LayerRow
                label={t('仅当前有效')}
                checked={settings.onlyActive}
                onToggle={() => patch({ onlyActive: !settings.onlyActive })}
              />
              <LayerRow
                label={t('显示已失效')}
                checked={settings.showInvalidated}
                onToggle={() => patch({ showInvalidated: !settings.showInvalidated })}
              />
            </Card>
          </div>
        </div>
      </div>
    </>,
    document.body,
  );
}
