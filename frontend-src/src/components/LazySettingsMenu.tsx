import { useCallback, useEffect, useRef, useState, type ComponentType } from 'react';
import Icon from '@/components/icons';
import { t } from '@/i18n/core';
import type { SettingsMenuProps } from './SettingsMenu';

type Menu = ComponentType<SettingsMenuProps>;
let ready: Menu | null = null;
let pending: Promise<Menu> | null = null;
function prepare(): Promise<Menu> {
  if (ready) return Promise.resolve(ready);
  if (!pending) pending = import('./SettingsMenu').then((module) => { ready = module.default; return ready; })
    .catch((error: unknown) => { pending = null; throw error; });
  return pending;
}
/** Keep the trigger and its icon mounted while only menu content loads on demand. */
export default function LazySettingsMenu() {
  const [Menu, setMenu] = useState<Menu | null>(() => ready);
  const wantsOpen = useRef(false);
  const trigger = useRef<HTMLButtonElement>(null);
  const container = useRef<HTMLDivElement>(null);
  const [opening, setOpening] = useState(false);
  const changeOpen = useCallback((open: boolean) => { wantsOpen.current = open; setOpening(open); }, []);
  const cancel = useCallback(() => changeOpen(false), [changeOpen]);
  useEffect(() => {
    if (!opening || Menu) return;
    const outside = (event: PointerEvent) => {
      if (!trigger.current?.contains(event.target as Node)) cancel();
    };
    const key = (event: KeyboardEvent) => {
      if (event.key === 'Escape' || event.key === 'Tab') cancel();
    };
    document.addEventListener('pointerdown', outside);
    document.addEventListener('keydown', key);
    return () => {
      document.removeEventListener('pointerdown', outside);
      document.removeEventListener('keydown', key);
    };
  }, [opening, Menu, cancel]);
  const load = (show = false) => {
    if (show) changeOpen(true);
    void prepare().then((Component) => {
      if (wantsOpen.current) setMenu(() => Component);
    }).catch(cancel);
  };
  return <div ref={container} className="relative"><button ref={trigger} type="button" className="icon-motion-trigger touch-target header-action"
    aria-haspopup="menu" aria-expanded={Boolean(Menu && opening)} aria-busy={opening && !Menu || undefined} aria-label={t('显示设置')} title={t('显示设置')}
    onPointerEnter={() => load()} onFocus={() => load()} onBlur={() => { if (!Menu) cancel(); }}
    onClick={() => { if (opening) cancel(); else load(true); }}
    onKeyDown={(event) => {
      if (event.key === 'Escape') cancel();
      if (event.key === 'ArrowDown' || event.key === 'ArrowUp') { event.preventDefault(); load(true); }
    }}><span className="header-chip"><Icon name="sliders" size={15} motion /></span></button>
    {Menu && <Menu open={opening} setOpen={changeOpen} containerRef={container} triggerRef={trigger} />}
  </div>;
}
