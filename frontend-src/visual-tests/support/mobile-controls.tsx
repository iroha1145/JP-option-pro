import { useState } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router';
import { AccessProvider } from '../../src/hooks/useAccess';
import CommandPalette from '../../src/components/CommandPalette';
import ScanHistoryPopover from '../../src/components/screener/ScanHistoryPopover';
import MenuSelect from '../../src/components/shared/MenuSelect';
import InfoHint from '../../src/components/shared/InfoHint';
import { STRUCTURE_HINTS, TECHNICAL_HINTS } from '../../src/lib/indicatorHints';
import SettingsMenu from '../../src/components/SettingsMenu';
import { ToastProvider } from '../../src/components/Toast';
import { useToast } from '../../src/hooks/useToast';
import PageHeader from '../../src/components/shared/PageHeader';
import { DataThrough } from '../../src/components/domain';
import ForceRefreshButton from '../../src/components/shared/ForceRefreshButton';
import { t } from '../../src/i18n/core';
import '../../src/styles/transitions-root.css';
import '../../src/index.css';
import '../../src/styles/transitions-catalog.css';

function App() {
  const [palette, setPalette] = useState(false);
  const [option, setOption] = useState('0');
  const [clicks, setClicks] = useState(0);
  const toast = useToast();
  return <main className="p-4">
    <div className="flex items-center gap-3"><button id="open-palette" onClick={() => setPalette(true)}>Search</button><ScanHistoryPopover history={[]} /></div>
    <div id="settings" className="absolute right-2 top-2"><SettingsMenu /></div>
    <button id="show-toast" onClick={() => toast.error("通知标题", "需要保留的错误说明")}>Notify</button>
    <MenuSelect ariaLabel="Regression menu" value={option} onChange={setOption} options={Array.from({ length: 20 }, (_, i) => ({ value: String(i), label: `Option ${i}` }))} />
    <div id="hint-parent" onClick={() => setClicks(n => n + 1)} style={{ position: 'absolute', left: 24, top: 110 }}>
      <InfoHint hint={STRUCTURE_HINTS.base_detection} side="bottom" />
    </div>
    <div id="short-hint" style={{ position: 'absolute', right: 24, top: 110 }}><InfoHint hint={TECHNICAL_HINTS.macd} side="bottom" /></div>
    <output id="parent-clicks">{clicks}</output>
    <button id="outside" style={{ position: 'absolute', bottom: 8, right: 8 }}>Outside</button>
    <CommandPalette open={palette} onClose={() => setPalette(false)} onOpenTicker={() => setPalette(false)} />
  </main>;
}
// Use the production page header and its real meta controls; keep its wrapping
// and the outer Layout content width identical to Screener.tsx/Layout.tsx.
function ScanHistoryHeader() {
  const populated = new URLSearchParams(location.search).has('populated');
  const history = populated ? Array.from({ length: 5 }, (_, i) => ({
    at: Date.UTC(2026, 9, 23, 6, i), count: 20 + i, durationMs: 80,
    summary: t('条件选股'), kind: i === 0 ? 'refresh' as const : 'filter' as const,
  })) : [];
  return <main className="mx-auto w-full max-w-shell min-h-[100dvh] flex-1 scroll-mt-24 px-4 pt-6 md:px-8 md:pt-8">
    <PageHeader section="screener" title={t('条件选股')}
      description={t('收盘后按日线全市场计算强度分，扫描读取已保存发布，不会触发供应商。')}
      meta={<>
        <DataThrough date={populated ? '2026-10-23' : null} />
        {populated && <span className="hidden text-right sm:block"><span className="block text-micro text-ink-400">{t('评分时间')}</span><span className="tnum text-caption text-ink-600">15:00:00</span></span>}
        {populated && <span className="hidden text-right sm:block"><span className="block text-micro text-ink-400">{t('上次筛选')}</span><span className="tnum text-caption text-ink-600">15:04:00</span></span>}
        <ScanHistoryPopover history={history} />
        <ForceRefreshButton onClick={() => {}} label={t('重新读取')} title={t('按当前条件重新读取已保存发布，不会重算日线')} testId="screener-reread" />
      </>}
    />
    <button id="history-outside" className="mt-8">Outside</button>
  </main>;
}
const preview = new URLSearchParams(location.search).has('scan-history') ? <ScanHistoryHeader /> : <App />;
createRoot(document.getElementById('root')!).render(<BrowserRouter><AccessProvider><ToastProvider>{preview}</ToastProvider></AccessProvider></BrowserRouter>);
