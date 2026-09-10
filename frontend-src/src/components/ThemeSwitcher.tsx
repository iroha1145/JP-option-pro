/**
 * 外观切换：跟随系统 / 浅色 / 深色。
 * 桌面与手机都挂在右上角；登录页没有顶栏时用 corner 变体固定到右上。
 */
import { useEffect, useRef, useState } from 'react';
import { cn } from '@/lib/utils';
import {
  overlayClassName,
  overlayVisible,
  readRootDurationMs,
  useOverlayPhase,
} from '@/lib/transitions';
import { setThemePreference, type ThemePreference } from '@/lib/themePreference.ts';
import { useTheme, useThemePreference } from '@/hooks/useTheme.ts';
import Icon, { type IconName } from '@/components/icons';
import { t } from '../i18n/core.ts';

const OPTIONS: { value: ThemePreference; label: string; icon: IconName }[] = [
  { value: 'system', label: t('跟随系统'), icon: 'desktop' },
  { value: 'light', label: t('浅色'), icon: 'sun-bmo' },
  { value: 'dark', label: t('深色'), icon: 'moon-amc' },
];

function preferenceIcon(preference: ThemePreference, resolved: 'light' | 'dark'): IconName {
  if (preference === 'system') return 'desktop';
  return resolved === 'dark' ? 'moon-amc' : 'sun-bmo';
}

export default function ThemeSwitcher({
  className,
  corner = false,
}: {
  className?: string;
  corner?: boolean;
}) {
  const preference = useThemePreference();
  const resolved = useTheme();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const listRef = useRef<HTMLUListElement>(null);
  const closeMs = readRootDurationMs('--dropdown-close-dur', 150);
  const phase = useOverlayPhase(open, closeMs);
  const mounted = overlayVisible(open, phase);
  const tip = preference === 'system'
    ? t('当前：跟随系统（{mode}）', { mode: resolved === 'dark' ? t('深色') : t('浅色') })
    : preference === 'dark'
      ? t('当前：深色模式')
      : t('当前：浅色模式');

  useEffect(() => {
    if (!open) return;
    const target =
      listRef.current?.querySelector<HTMLButtonElement>('[role="menuitemradio"][aria-checked="true"]') ??
      listRef.current?.querySelector<HTMLButtonElement>('[role="menuitemradio"]');
    target?.focus();
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setOpen(false);
        triggerRef.current?.focus();
      }
    };
    document.addEventListener('mousedown', onDoc);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDoc);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  const onMenuKeyDown = (e: React.KeyboardEvent<HTMLUListElement>) => {
    const items = Array.from(
      listRef.current?.querySelectorAll<HTMLButtonElement>('[role="menuitemradio"]') ?? [],
    );
    if (!items.length) return;
    const idx = items.indexOf(document.activeElement as HTMLButtonElement);
    let target = -1;
    if (e.key === 'ArrowDown') target = Math.min(idx + 1, items.length - 1);
    else if (e.key === 'ArrowUp') target = Math.max(idx - 1, 0);
    else if (e.key === 'Home') target = 0;
    else if (e.key === 'End') target = items.length - 1;
    else return;
    e.preventDefault();
    items[target]?.focus();
  };

  return (
    <div ref={ref} className={cn(corner ? 'fixed right-3 top-3 z-[70] md:right-5 md:top-4' : 'relative', className)}>
      <button
        ref={triggerRef}
        type="button"
        onClick={() => setOpen((v) => !v)}
        onKeyDown={(e) => {
          if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
            e.preventDefault();
            setOpen(true);
          }
        }}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={t('切换外观')}
        data-theme-switcher=""
        title={tip}
        className={cn(
          'theme-control inline-flex size-9 shrink-0 items-center justify-center rounded-md border border-line bg-card text-ink-500 shadow-btn transition-colors duration-fast hover:bg-paper hover:text-ink-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ink-400 md:h-8 md:w-8',
          open && 'border-brand-400 text-brand-600',
        )}
      >
        <Icon name={preferenceIcon(preference, resolved)} size={16} />
      </button>
      {mounted && (
        <div
          role="menu"
          aria-label={t('外观')}
          data-origin="top-right"
          className={cn(
            't-dropdown absolute right-0 top-11 z-40 w-[176px] rounded-md border border-line bg-card p-1.5 shadow-sh-2 md:top-10',
            overlayClassName(phase),
          )}
        >
          <p className="px-2 pb-1.5 pt-1 eyebrow">{t('外观')}</p>
          <ul ref={listRef} onKeyDown={onMenuKeyDown}>
            {OPTIONS.map((option) => {
              const active = option.value === preference;
              return (
                <li key={option.value}>
                  <button
                    role="menuitemradio"
                    aria-checked={active}
                    data-theme-option={option.value}
                    onClick={() => {
                      setThemePreference(option.value);
                      setOpen(false);
                    }}
                    className={cn(
                      'flex w-full items-center gap-2 rounded-xs px-2 py-1.5 text-left text-body-s transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-500/30',
                      active ? 'text-brand-600' : 'text-ink-700 hover:bg-paper-2',
                    )}
                  >
                    <Icon name={option.icon} size={14} className="shrink-0 text-ink-400" />
                    <span className="flex-1">{option.label}</span>
                    {active && <Icon name="check" size={13} className="shrink-0" />}
                  </button>
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </div>
  );
}
