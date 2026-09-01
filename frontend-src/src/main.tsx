import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App.tsx';
import './index.css';

// Self-heal a failed lazy-route chunk load. Routes are code-split, so if the app
// is open across a redeploy (chunk hashes change) a client-side navigation can throw
// "Failed to fetch dynamically imported module" and leave a blank page until a manual
// refresh. Vite dispatches `vite:preloadError` on that failure — reload once (guarded
// against loops) so the user lands on the fresh bundle instead of a white screen.
window.addEventListener('vite:preloadError', () => {
  const KEY = 'optixjp:preload-reloaded';
  try {
    if (sessionStorage.getItem(KEY)) return; // already reloaded once; avoid a loop
    sessionStorage.setItem(KEY, String(Date.now()));
  } catch {
    /* private mode: still attempt the reload below */
  }
  window.location.reload();
});
// Clear the one-shot guard once a load succeeds, so a later genuine failure can reload again.
window.addEventListener('load', () => {
  try {
    sessionStorage.removeItem('optixjp:preload-reloaded');
  } catch {
    /* ignore */
  }
});

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
