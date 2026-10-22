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
createRoot(document.getElementById('root')!).render(<BrowserRouter><AccessProvider><ToastProvider><App /></ToastProvider></AccessProvider></BrowserRouter>);
