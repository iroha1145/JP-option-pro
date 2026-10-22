import { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router';
import MobileDock from '../../src/components/MobileDock';
import { AccessProvider } from '../../src/hooks/useAccess';
import { ToastProvider } from '../../src/components/Toast';
import Switch from '../../src/components/shared/Switch';
import { useFeelSheetDrag } from '../../src/hooks/useFeelMagneticSheet';
import '../../src/styles/transitions-root.css';
import '../../src/index.css';
import '../../src/styles/transitions-catalog.css';
export function Sheet({ enabled, close }: { enabled: boolean; close: () => void }) {
  const panelRef = useRef<HTMLDivElement>(null);
  const backdropRef = useRef<HTMLDivElement>(null);
  const drag = useFeelSheetDrag({ panelRef, backdropRef, onClose: close, enabled });
  return <><div ref={backdropRef} id="sheet-backdrop" className="t-backdrop is-open" style={{ position: 'absolute', inset: 0, background: 'rgba(0, 0, 0, .12)', pointerEvents: 'none' }} /><div ref={panelRef} id="sheet" data-feel-sheet data-enabled={enabled} className="t-panel-slide" data-open="true" style={{ position: 'absolute', top: 150, left: 20, width: 300, height: 500, background: '#ddd' }}>
    <button type="button" data-handle id="handle" style={{ width: '100%', height: 48, background: '#aaa' }} {...drag}>拖动</button>
  </div></>;
}
export function App() {
  const [checked, setChecked] = useState(false);
  const [disabled, setDisabled] = useState(false);
  const [enabled, setEnabled] = useState(true);
  const [mounted, setMounted] = useState(true);
  const [closes, setCloses] = useState(0);
  const [rowClicks, setRowClicks] = useState(0);
  useEffect(() => {
    Object.assign(window, { gestureControls: { disable: () => setDisabled(true), close: () => setEnabled(false), unmount: () => setMounted(false) } });
  }, []);
  return <>
    <MobileDock />
    <div style={{ margin: 40 }} onClick={() => setRowClicks(n => n + 1)}><Switch label="测试开关" checked={checked} disabled={disabled} onToggle={() => setChecked(x => !x)} /></div>
    <output id="state">{String(checked)}</output><output id="closes">{closes}</output><output id="rows">{rowClicks}</output>
    {mounted && <Sheet enabled={enabled} close={() => { setCloses(n => n + 1); setEnabled(false); }} />}</>;
}
createRoot(document.getElementById('root')!).render(<BrowserRouter><AccessProvider><ToastProvider><App /></ToastProvider></AccessProvider></BrowserRouter>);
