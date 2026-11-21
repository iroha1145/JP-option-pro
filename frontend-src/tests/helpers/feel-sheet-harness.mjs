import fs from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';
import { MagneticSheetBody } from '../../src/lib/magneticSheet.ts';
import { createReactStub } from './feel-react-hooks.mjs';

export function sheetHarness(sourceUrl = new URL('../../src/hooks/useFeelMagneticSheet.ts', import.meta.url)) {
  let now = 0, id = 0, closed = 0, enabled = true;
  const frames = new Map(), listeners = new Map(), preferences = new Set(), animations = [];
  const media = { matches: false, addEventListener: (_, fn) => preferences.add(fn), removeEventListener: (_, fn) => preferences.delete(fn) };
  const react = createReactStub(); react.React.useLayoutEffect = react.React.useEffect;
  const module = { exports: {} };
  const makeElement = () => ({ style: { transform: '', transition: '', opacity: '' }, dataset: {}, offsetHeight: 600,
    animate(keyframes, options) {
      const animation = { keyframes, options, currentTime: 0, onfinish: null, cancelled: false, startTime: null,
        cancel() { this.cancelled = true; }, finish() { this.onfinish?.(); } };
      animations.push(animation); this.animation = animation; return animation;
    },
  });
  const panel = makeElement(), backdrop = makeElement(), captures = new Set();
  const handle = { setPointerCapture: n => captures.add(n), hasPointerCapture: n => captures.has(n), releasePointerCapture: n => captures.delete(n) };
  const yOf = transform => Number(transform?.match(/translate3d\(0, ([\d.e+-]+)px/)?.[1] ?? 0);
  const computedY = () => {
    const a = panel.animation;
    if (!a || a.cancelled) return yOf(panel.style.transform);
    const frame = Math.max(0, Math.min(a.keyframes.length - 1, a.currentTime / a.options.duration * (a.keyframes.length - 1)));
    const index = Math.floor(frame), first = yOf(a.keyframes[index].transform), last = yOf(a.keyframes[Math.min(index+1,a.keyframes.length-1)].transform);
    return first + (last-first) * (frame-index);
  };
  const source = ts.transpileModule(fs.readFileSync(sourceUrl, 'utf8'), { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS } }).outputText;
  vm.runInNewContext(source, { module, exports: module.exports,
    require: name => name === 'react' ? react.React : { MagneticSheetBody },
    window: { matchMedia: () => media, addEventListener: (name, fn) => listeners.set(name, fn), removeEventListener: name => listeners.delete(name) },
    document: { timeline: { currentTime: 123 } },
    getComputedStyle: () => ({ transform: String(computedY()) }), DOMMatrixReadOnly: class { constructor(v) { this.m42 = Number(v); } },
    performance: { now: () => now }, requestAnimationFrame: fn => { frames.set(++id, fn); return id; }, cancelAnimationFrame: n => frames.delete(n),
  });
  const panelRef = { current: panel }, backdropRef = { current: backdrop };
  let api;
  react.mount(() => { api = module.exports.useFeelSheetDrag({ panelRef, backdropRef, enabled, onClose: () => { closed++; } }); });
  return { panel, backdrop, animations, frames, captures, listeners, preferences, get api() { return api; }, get closed() { return closed; },
    pointer(method, y, pointerId = 1) { api[method]({ pointerId, button: 0, isPrimary: true, clientY: y, currentTarget: handle }); },
    advance(ms) { for (let elapsed=0; elapsed<ms; elapsed+=4) { now+=4; const batch=[...frames.values()]; frames.clear(); batch.forEach(fn => fn(now)); } },
    blur() { listeners.get('blur')?.(); }, resize() { listeners.get('resize')?.(); },
    reduce() { media.matches=true; preferences.forEach(fn => fn()); },
    disable() { enabled=false; react.rerender(); }, unmount: react.unmount,
  };
}
