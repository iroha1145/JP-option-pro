import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router';
import './styles/transitions-root.css';
import './index.css';
import './styles/transitions-catalog.css';
import { applyColorMode } from './lib/colorPreference.ts';
import App from './App.tsx';

applyColorMode();

window.addEventListener('vite:preloadError', (event) => {
  const KEY = 'optixjp:preload-reloaded';
  const now = Date.now();
  try {
    const last = Number(sessionStorage.getItem(KEY) ?? 0);
    if (now - last < 10_000) return;
    sessionStorage.setItem(KEY, String(now));
  } catch {
    /* private mode: still attempt the reload below */
  }
  event.preventDefault();
  window.location.reload();
});

createRoot(document.getElementById('root')!).render(
  <BrowserRouter>
    <App />
  </BrowserRouter>,
);
