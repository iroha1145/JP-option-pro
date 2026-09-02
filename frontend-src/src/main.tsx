import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App.tsx';
import './index.css';

// Self-heal a failed lazy-route chunk load. Routes are code-split, so if the app
// is open across a redeploy (chunk hashes change) a client-side navigation can throw
// "Failed to fetch dynamically imported module" and leave a blank page until a manual
// refresh. Vite dispatches `vite:preloadError` on that failure — reload once (guarded
// against loops) so the user lands on the fresh bundle instead of a white screen.
// Loop guard is a time window, not a flag cleared on `load`: if a chunk is genuinely
// missing (broken deploy) the failure recurs after every reload, and clearing on `load`
// would reload forever. At most one automatic reload per 10s; otherwise let the error
// surface so the route error boundary can show it.
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
  <StrictMode>
    <App />
  </StrictMode>,
);
