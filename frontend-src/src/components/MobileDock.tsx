/**
 * 移动端底部 Dock — 对标美版（悬浮胶囊 + 「更多」上弹 sheet）。
 * 四个高频入口直达；其余页面（首页/决算日历/新闻/数据状态）、界面语言、
 * 登录状态全部收进 sheet —— 底部导航覆盖全部跳转。
 */
import { useEffect, useRef, useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router';
import { AnimatePresence, motion } from 'framer-motion';
import { cn } from '@/lib/utils';
import { useAccess } from '@/hooks/useAccess';
import { useFocusTrap } from '@/hooks/useFocusTrap';
import { Icon, type IconName } from '@/components/icons';
import Segmented from '@/components/shared/Segmented';
import { LOCALES, getLocale, setLocale, t } from '@/i18n/core';

/* setLocale() 整页重载才会切语言，模块级常量在加载期求值一次即可 */
const DOCK_ITEMS: { label: string; path: string; icon: IconName }[] = [
  { label: t('自选'), path: '/watchlist', icon: 'star-line' },
  { label: t('雷达'), path: '/radar', icon: 'radar' },
  { label: t('筛选'), path: '/screener', icon: 'filter-funnel' },
  { label: t('市场'), path: '/market', icon: 'candle' },
];

const MORE_ITEMS: { label: string; path: string; icon: IconName; desc: string }[] = [
  { label: t('首页'), path: '/', icon: 'cards', desc: t('总览 · 今日市场焦点') },
  { label: t('决算日历'), path: '/earnings', icon: 'calendar-spark', desc: t('確定 · 目安三态日历') },
  { label: t('新闻'), path: '/news', icon: 'doc-quote', desc: t('催化剂 · 三源新闻流') },
  { label: t('数据状态'), path: '/data-status', icon: 'wallet-gauge', desc: t('同步进度 · 数据覆盖') },
  { label: t('历史验证'), path: '/research', icon: 'wallet-gauge', desc: t('走步验证 · 分层收益') },
];

export default function MobileDock() {
  const location = useLocation();
  const navigate = useNavigate();
  const { isOwner, accountUsername } = useAccess();
  const [moreOpen, setMoreOpen] = useState(false);
  /* aria-modal 配套：声明了模态就要真的困住焦点 */
  const sheetRef = useRef<HTMLDivElement | null>(null);
  useFocusTrap(sheetRef, moreOpen);
  /* 导航离开时同步强制关闭：sheet 卸载依赖 AnimatePresence 退场动画完成，
     重页面挂载会榨干低端手机主线程、退场被饿死时白色 sheet 会一直盖在新页
     面上。路由一变就立刻置 false。 */
  useEffect(() => {
    setMoreOpen(false);
  }, [location.pathname]);

  /* aria-modal 配套行为：Escape 可关 + 打开期间锁背景滚动 */
  useEffect(() => {
    if (!moreOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setMoreOpen(false);
    };
    document.addEventListener('keydown', onKey);
    document.body.style.overflow = 'hidden';
    return () => {
      document.removeEventListener('keydown', onKey);
      document.body.style.overflow = '';
    };
  }, [moreOpen]);

  const renderItem = (item: (typeof DOCK_ITEMS)[number]) => {
    const active = location.pathname.startsWith(item.path);
    return (
      <Link
        key={item.path}
        to={item.path}
        className="relative flex min-h-[44px] flex-1 flex-col items-center justify-center gap-1"
        aria-label={item.label}
        aria-current={active ? 'page' : undefined}
      >
        {/* 当前页的小标记：图标上方一枚 4px 圆点，比整块高亮安静 */}
        <span
          aria-hidden="true"
          className={cn(
            'absolute top-1.5 size-1 rounded-full bg-brand-600 transition-opacity duration-fast',
            active ? 'opacity-100' : 'opacity-0',
          )}
        />
        <Icon name={item.icon} size={19} className={active ? 'text-brand-600' : 'text-ink-400'} />
        <span className={cn('text-[10px] leading-none', active ? 'font-medium text-brand-600' : 'text-ink-400')}>{item.label}</span>
      </Link>
    );
  };

  return (
    <>
      {/* 悬浮胶囊 Dock：离屏 12px + safe-area、全圆角、毛玻璃 + 墨色浮起阴影 */}
      <nav
        className="glass fixed inset-x-3 bottom-[calc(env(safe-area-inset-bottom)+0.75rem)] z-[60] mx-auto flex h-16 max-w-md items-stretch rounded-2xl border border-line px-1.5 shadow-[0_18px_40px_-14px_rgba(16,24,40,0.30),0_4px_14px_-6px_rgba(16,24,40,0.14)] xl:hidden"
        aria-label={t('移动端导航')}
      >
        {DOCK_ITEMS.map(renderItem)}
        <button
          onClick={() => setMoreOpen(true)}
          className="flex min-h-[44px] flex-1 flex-col items-center justify-center gap-1"
          aria-label={t('更多')}
        >
          <Icon name="menu" size={19} className="text-ink-400" />
          <span className="text-[10px] leading-none text-ink-400">{t('更多')}</span>
        </button>
      </nav>

      {/* 「更多」上弹 sheet */}
      <AnimatePresence>
        {moreOpen && (
          <>
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.15 }}
              /* 不用 backdrop-blur：全屏背板的实时模糊是移动 GPU 掉帧的最大单项 */
              className="fixed inset-0 z-[64] bg-[rgba(13,22,38,.32)] xl:hidden"
              onClick={() => setMoreOpen(false)}
            />
            <motion.div
              initial={{ y: '100%' }}
              animate={{ y: 0 }}
              exit={{ y: '100%' }}
              /* 短 tween 取代 spring：主线程被重页面挂载抢走时，定长 tween 恢复
                 的第一帧已到终点，弹簧则会长时间停在半途 */
              transition={{ duration: 0.22, ease: [0.16, 1, 0.3, 1] }}
              ref={sheetRef}
              className="fixed inset-x-0 bottom-0 z-[65] rounded-t-xl border-t border-line bg-card pb-[calc(env(safe-area-inset-bottom)+16px)] shadow-sh-3 xl:hidden"
              role="dialog"
              aria-modal="true"
              aria-label={t('更多功能')}
            >
              <div className="flex justify-center pb-1 pt-2 text-ink-300">
                <Icon name="dots-grid" size={18} />
              </div>
              <p className="eyebrow px-5 pb-2 pt-1">{t('更多功能')}</p>
              <div className="px-3">
                <div className="flex items-center justify-between gap-3 rounded-md px-3 py-3">
                  <span className="flex items-center gap-3">
                    <span className="flex size-9 items-center justify-center rounded-md border border-line bg-card-warm text-brand-600">
                      <Icon name="languages" size={17} />
                    </span>
                    <span className="text-body-s font-medium text-ink-800">{t('界面语言')}</span>
                  </span>
                  <Segmented
                    options={LOCALES.map((l) => ({ value: l.code, label: l.short }))}
                    value={getLocale()}
                    onChange={(code) => setLocale(code)}
                  />
                </div>
                <div className="mx-3 my-2 border-t border-line" />
                {MORE_ITEMS.map((m) => (
                  <button
                    key={m.path}
                    onClick={() => {
                      setMoreOpen(false);
                      navigate(m.path);
                    }}
                    className="flex w-full items-center gap-3 rounded-md px-3 py-3 text-left transition-colors hover:bg-paper-2"
                  >
                    <span className="flex size-9 items-center justify-center rounded-md border border-line bg-card-warm text-brand-600">
                      <Icon name={m.icon} size={17} />
                    </span>
                    <span className="flex-1">
                      <span className="block text-body-s font-medium text-ink-800">{m.label}</span>
                      <span className="block text-micro text-ink-400">{m.desc}</span>
                    </span>
                    <Icon name="chevron-right" size={14} className="text-ink-300" />
                  </button>
                ))}
                <div className="mx-3 my-2 border-t border-line" />
                <button
                  onClick={() => {
                    setMoreOpen(false);
                    navigate('/login');
                  }}
                  className="flex w-full items-center gap-3 rounded-md px-3 py-3 text-left transition-colors hover:bg-paper-2"
                >
                  <span className={cn('flex size-9 items-center justify-center rounded-md border border-line', isOwner ? 'bg-up-50 text-up-700' : 'bg-card-warm text-ink-400')}>
                    <Icon name="shield" size={17} />
                  </span>
                  <span className="flex-1">
                    <span className="block text-body-s font-medium text-ink-800">
                      {isOwner ? t('Owner 已登录') : accountUsername ? t('已登录 {name}', { name: accountUsername }) : t('访客只读模式')}
                    </span>
                    <span className="block text-micro text-ink-400">
                      {isOwner ? t('可执行写操作') : accountUsername ? t('自选保存在账号里') : t('登录后可保存自选')}
                    </span>
                  </span>
                </button>
              </div>
            </motion.div>
          </>
        )}
      </AnimatePresence>
    </>
  );
}
