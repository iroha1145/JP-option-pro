/**
 * 命令面板：⌘K · 股票搜索 / 功能 / 最近
 */
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router';
import { ApiError } from '@/api/client';
import { stocksApi } from '@/api/modules';
import type { SearchResult } from '@/api/types';
import { useAccess } from '@/hooks/useAccess';
import { useFocusTrap } from '@/hooks/useFocusTrap';
import { useBodyScrollLock } from '@/hooks/useBodyScrollLock';
import { isTopFocusScope } from '@/lib/focusScope';
import { cn } from '@/lib/utils';
import {
  overlayClassName,
  overlayVisible,
  placeGlide,
  readRootDurationMs,
  useOverlayPhase,
} from '@/lib/transitions';
import { pushRecent, readRecent } from '@/lib/recentTickers';
import Icon, { type IconName } from '@/components/icons';
import CodeMark from '@/components/shared/CodeMark';
import DotsLoader from '@/components/shared/DotsLoader';
import SoftBadge from '@/components/shared/SoftBadge';
import PointerTooltip from '@/components/shared/PointerTooltip';
import { NAV_ITEMS } from '@/components/Navbar';
import { t } from '@/i18n/core';

interface PaletteProps {
  open: boolean;
  onClose: () => void;
  onOpenTicker: (ticker: string) => void;
  onForceRefresh?: () => void;
}

interface Entry {
  id: string;
  group: string;
  no?: string;
  title: string;
  mono?: boolean;
  hint?: string;
  ticker?: string;
  sector?: string;
  icon: IconName;
  action: () => void;
}

function searchErrorText(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.code === 429) {
      return error.retryAfter
        ? t('搜索请求较多，请 {n} 秒后重试', { n: Math.ceil(error.retryAfter) })
        : t('搜索请求较多，请稍后重试');
    }
    if (error.code === 401) return t('登录状态已失效，请重新登录');
    if (error.code === 503) return t('股票目录暂不可用，请稍后重试');
    return error.message || t('股票搜索失败，请稍后重试');
  }
  return error instanceof Error && error.message
    ? error.message
    : t('股票搜索失败，请稍后重试');
}

function Kbd({ children }: { children: React.ReactNode }) {
  return (
    <kbd className="rounded-xs border border-line bg-card-warm px-1.5 py-0.5 font-mono text-[10px] leading-[14px] text-ink-400">
      {children}
    </kbd>
  );
}

export default function CommandPalette({ open, onClose, onOpenTicker, onForceRefresh }: PaletteProps) {
  const navigate = useNavigate();
  const { isOwner, isSignedIn, username, logout } = useAccess();
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<SearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const glideRef = useRef<HTMLSpanElement>(null);
  const glidePainted = useRef(false);
  const glideBatch = useRef<Entry[] | null>(null);
  useFocusTrap(panelRef, open, { initialFocusRef: inputRef });
  const closeMs = readRootDurationMs('--modal-close-dur', 150);
  const phase = useOverlayPhase(open, closeMs);
  const mounted = overlayVisible(open, phase);
  useBodyScrollLock(mounted);

  useEffect(() => {
    if (mounted) return;
    setQuery('');
    setResults([]);
    setSearchError(null);
    setActive(0);
  }, [mounted]);

  useEffect(() => {
    if (!open) return;
    const frame = requestAnimationFrame(() => inputRef.current?.focus());
    return () => cancelAnimationFrame(frame);
  }, [open]);

  useEffect(() => {
    const q = query.trim();
    if (!open || !q) {
      setResults([]);
      setSearching(false);
      setSearchError(null);
      return;
    }
    setResults([]);
    setSearching(true);
    setSearchError(null);
    let cancelled = false;
    const timer = window.setTimeout(async () => {
      try {
        const next = await stocksApi.search(q);
        if (!cancelled) {
          setResults(next.results);
          setSearchError(null);
        }
      } catch (cause) {
        if (!cancelled) {
          setResults([]);
          setSearchError(searchErrorText(cause));
        }
      } finally {
        if (!cancelled) setSearching(false);
      }
    }, 200);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [query, open]);

  const pickTicker = useCallback(
    (code: string) => {
      pushRecent(code);
      onClose();
      onOpenTicker(code);
    },
    [onClose, onOpenTicker],
  );

  const entries = useMemo<Entry[]>(() => {
    const list: Entry[] = [];
    if (query.trim()) {
      results.forEach((r) =>
        list.push({
          id: `s-${r.canonical_code}`,
          group: t('股票'),
          title: r.display_code,
          mono: true,
          hint: r.name_ja ?? r.name_en ?? undefined,
          ticker: r.display_code,
          sector: r.market_name ?? undefined,
          icon: 'candle',
          action: () => pickTicker(r.display_code),
        }),
      );
    } else {
      readRecent().forEach((code) =>
        list.push({
          id: `r-${code}`,
          group: t('最近'),
          title: code,
          ticker: code,
          mono: true,
          hint: t('最近查看'),
          icon: 'clock-ny',
          action: () => pickTicker(code),
        }),
      );
      NAV_ITEMS.forEach((n) =>
        list.push({
          id: `f-${n.path}`,
          group: t('功能'),
          no: n.no,
          title: n.label,
          hint: t('前往{label}', { label: n.label }),
          icon: 'chevron-right',
          action: () => {
            onClose();
            navigate(n.path);
          },
        }),
      );
      list.push(
        {
          id: 'f-data',
          group: t('功能'),
          title: t('数据状态'),
          hint: t('同步进度 · 数据覆盖'),
          icon: 'wallet-gauge',
          action: () => {
            onClose();
            navigate('/data-status');
          },
        },
        {
          id: 'f-research',
          group: t('功能'),
          title: t('历史验证'),
          hint: t('走步验证 · 分层收益'),
          icon: 'wallet-gauge',
          action: () => {
            onClose();
            navigate('/research');
          },
        },
      );
      if (isOwner) {
        list.push({
          id: 'f-refresh',
          group: t('功能'),
          title: t('强制刷新自选'),
          hint: t('重新获取自选行情'),
          icon: 'refresh',
          action: () => {
            onClose();
            onForceRefresh?.();
          },
        });
        list.push({
          id: 'f-logout',
          group: t('功能'),
          title: t('退出 Owner 登录'),
          hint: t('结束本机会话'),
          icon: 'shield',
          action: () => {
            onClose();
            void logout();
          },
        });
      } else if (isSignedIn) {
        list.push({
          id: 'f-logout',
          group: t('功能'),
          title: username ? t('退出 {name}', { name: username }) : t('退出登录'),
          hint: t('结束本机会话'),
          icon: 'shield',
          action: () => {
            onClose();
            void logout();
          },
        });
      } else {
        list.push({
          id: 'f-login',
          group: t('功能'),
          title: t('登录'),
          hint: t('Owner 或访客账号'),
          icon: 'shield',
          action: () => {
            onClose();
            navigate('/login');
          },
        });
      }
    }
    return list;
  }, [query, results, navigate, onClose, onForceRefresh, pickTicker, isOwner, isSignedIn, username, logout]);

  const flat = entries;
  const clampedActive = Math.min(active, Math.max(0, flat.length - 1));

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.defaultPrevented || e.nativeEvent.isComposing || e.nativeEvent.keyCode === 229 || !isTopFocusScope(panelRef.current)) return;
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setActive(flat.length ? (clampedActive + 1) % flat.length : 0);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setActive(flat.length ? (clampedActive - 1 + flat.length) % flat.length : 0);
    } else if (e.key === 'Enter') {
      const target = e.target as HTMLElement;
      if (target.closest('button, a, [role="button"]')) return;
      e.preventDefault();
      flat[clampedActive]?.action();
    } else if (e.key === 'Escape') {
      e.preventDefault();
      e.stopPropagation();
      onClose();
    }
  };

  useEffect(() => {
    const el = listRef.current?.querySelector<HTMLElement>(`[data-idx="${clampedActive}"]`);
    el?.scrollIntoView({ block: 'nearest' });
  }, [clampedActive]);

  useLayoutEffect(() => {
    if (!mounted) {
      glidePainted.current = false;
      glideBatch.current = null;
      return;
    }
    const glide = glideRef.current;
    const row = listRef.current?.querySelector<HTMLElement>(`[data-idx="${clampedActive}"]`);
    if (!glide || !row || entries.length === 0) {
      if (glide) glide.style.opacity = '0';
      glidePainted.current = false;
      glideBatch.current = null;
      return;
    }
    const sameBatch = glideBatch.current === entries;
    placeGlide(
      glide,
      { offset: row.offsetTop, size: row.offsetHeight },
      { axis: 'y', animate: glidePainted.current && sameBatch },
    );
    glide.style.opacity = '1';
    glidePainted.current = true;
    glideBatch.current = entries;
  }, [mounted, clampedActive, entries]);

  const groups: { name: string; items: (Entry & { idx: number })[] }[] = [];
  flat.forEach((e, idx) => {
    const g = groups.find((x) => x.name === e.group);
    const item = { ...e, idx };
    if (g) g.items.push(item);
    else groups.push({ name: e.group, items: [item] });
  });

  if (!mounted) return null;

  return (
    <>
      <div
        className={cn('t-backdrop fixed inset-0 z-[80] bg-[rgba(13,22,38,.28)] backdrop-blur-[2px]', phase === 'open' && 'is-open')}
        onClick={onClose}
        data-focus-backdrop="command-palette"
        aria-hidden="true"
      />
      <div className="pointer-events-none fixed left-1/2 top-[18vh] z-[81] w-[640px] max-w-[calc(100vw-24px)] -translate-x-1/2">
        <div
          ref={panelRef}
          role="dialog"
          aria-modal="true"
          data-focus-overlay="command-palette"
          aria-label={t('命令面板')}
          onKeyDown={onKeyDown}
          className={cn(
            't-modal overflow-hidden rounded-lg border border-line-strong bg-card/[0.88] backdrop-blur-xl backdrop-saturate-150 shadow-overlay',
            overlayClassName(phase),
          )}
        >
          <div className="flex h-12 items-center gap-2.5 border-b border-line px-4">
            <Icon name="search" size={16} className="shrink-0 text-ink-400" />
            <input
              ref={inputRef}
              value={query}
              onChange={(e) => {
                setQuery(e.target.value);
                setSearchError(null);
                setActive(0);
              }}
              placeholder={t('搜索股票代码、名称或功能…')}
              className="h-full min-w-0 w-0 flex-1 bg-transparent text-body text-ink-800 outline-none placeholder:text-ink-300 focus-visible:!shadow-none"
              role="combobox"
              aria-expanded={open}
              aria-autocomplete="list"
              aria-controls="command-palette-listbox"
              aria-activedescendant={flat.length ? `command-palette-option-${clampedActive}` : undefined}
              aria-label={t('搜索股票或功能')}
            />
            {searching ? (
              <DotsLoader label={t('搜索中')} />
            ) : query ? (
              <button
                type="button"
                aria-label={t('清除搜索')}
                onClick={() => {
                  setQuery('');
                  setSearchError(null);
                  setActive(0);
                  inputRef.current?.focus();
                }}
                className="anim-fade-in flex size-6 shrink-0 items-center justify-center rounded-md text-ink-400 transition-colors duration-fast hover:bg-line/70 hover:text-ink-800"
              >
                <Icon name="x" size={12} />
              </button>
            ) : (
              <Kbd>ESC</Kbd>
            )}
          </div>

          <div id="command-palette-listbox" role="listbox" ref={listRef} className="relative max-h-[46vh] overflow-y-auto py-1.5">
            <span
              ref={glideRef}
              aria-hidden="true"
              data-glide-list=""
              className="pointer-events-none absolute inset-x-1.5 top-0 z-0 rounded-md bg-brand-50"
              style={{
                height: 0,
                opacity: 0,
                transition:
                  'transform var(--tabs-dur) var(--tabs-ease), height var(--tabs-dur) var(--tabs-ease), opacity var(--duration-quick)',
              }}
            >
              <span className="absolute inset-y-1 left-0 w-0.5 rounded-full bg-brand-600" />
            </span>
            {searching && flat.length === 0 && (
              <div className="flex flex-col items-center py-10 text-center" role="status">
                <DotsLoader />
                <p className="mt-3 text-body-s text-ink-400">{t('正在搜索股票目录…')}</p>
              </div>
            )}
            {!searching && searchError && (
              <div className="flex flex-col items-center px-6 py-10 text-center" role="alert" aria-live="assertive">
                <span className="flex size-9 items-center justify-center rounded-full bg-down-50 text-down-700">
                  <Icon name="x" size={15} />
                </span>
                <p className="mt-3 text-body-s font-medium text-ink-700">{t('搜索未完成')}</p>
                <p className="mt-1 max-w-sm text-micro leading-5 text-ink-400">{searchError}</p>
              </div>
            )}
            {!searching && !searchError && flat.length === 0 && (
              <div className="anim-fade-in flex flex-col items-center py-10 text-center">
                <span className="flex size-9 items-center justify-center rounded-lg border border-line bg-card-warm text-ink-300 shadow-[inset_0_1px_2px_rgba(16,24,40,.05)]">
                  <Icon name="search" size={16} />
                </span>
                <p className="mt-3 text-body-s font-medium text-ink-700">{t('没有匹配的结果')}</p>
                <p className="mt-1 text-micro text-ink-400">
                  {t('试试代码')} <span className="font-mono">7203</span> {t('或日文名（トヨタ）')}
                </p>
              </div>
            )}
            {groups.map((g) => (
              <div key={g.name}>
                <p className="eyebrow relative z-10 px-4 pb-1 pt-2.5">{g.name}</p>
                {g.items.map((e) => (
                  <button
                    key={e.id}
                    id={`command-palette-option-${e.idx}`}
                    role="option"
                    aria-selected={e.idx === clampedActive}
                    data-idx={e.idx}
                    onClick={e.action}
                    onMouseEnter={() => setActive(e.idx)}
                    onFocus={() => setActive(e.idx)}
                    className="relative z-10 flex w-full items-center gap-2.5 rounded-md px-4 py-2 text-left transition-colors duration-fast"
                  >
                    {e.ticker ? <CodeMark code={e.ticker} size={24} /> : <Icon name={e.icon} size={15} className={cn('shrink-0', e.idx === clampedActive ? 'text-brand-600' : 'text-ink-400')} />}
                    {e.no && <span className="font-mono text-micro text-ink-400 tnum">{e.no}</span>}
                    <span
                      className={cn(
                        e.mono ? 'font-mono text-body-s font-medium' : 'text-body-s',
                        e.idx === clampedActive ? 'text-ink-900' : 'text-ink-700',
                      )}
                    >
                      {e.title}
                    </span>
                    {(e.hint || e.sector) && (
                      <span className="ml-auto flex min-w-0 max-w-[58%] items-center gap-1.5">
                        {e.hint && <span className="min-w-0 truncate text-micro text-ink-400">{e.hint}</span>}
                        {e.sector && (
                          <PointerTooltip
                            passthrough
                            label={e.sector}
                            width={180}
                            contentClassName="p-2"
                            content={<span className="text-micro text-ink-600">{e.sector}</span>}
                          >
                            <SoftBadge className="max-w-[7rem] shrink-0">
                              <span className="truncate">{e.sector}</span>
                            </SoftBadge>
                          </PointerTooltip>
                        )}
                      </span>
                    )}
                  </button>
                ))}
              </div>
            ))}
          </div>

          <div className="flex items-center gap-3 border-t border-line bg-card-warm px-4 py-2 text-micro text-ink-400">
            <span className="flex items-center gap-1.5"><Kbd>↑↓</Kbd> {t('选择')}</span>
            <span className="flex items-center gap-1.5"><Kbd>Enter</Kbd> {t('打开')}</span>
            <span className="flex items-center gap-1.5"><Kbd>Esc</Kbd> {t('关闭')}</span>
          </div>
        </div>
      </div>
    </>
  );
}
