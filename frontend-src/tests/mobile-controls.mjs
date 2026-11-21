import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';
const jsx = (type, props) => ({ type, props });
const nodes = tree => !tree || typeof tree !== 'object' ? [] : Array.isArray(tree) ? tree.flatMap(nodes) : [tree, ...nodes(tree.props?.children)];

// Execute the actual component. Deterministic boxes isolate viewport/event
// behavior; mobile-controls.spec.mjs verifies real font wrapping and scrolling.
function setup({ contentHeight = 360, visualHeight = 180, visualTop = 0 } = {}) {
  const slots = []; let cursor = 0; let tree; let rendering = false; let queued = false; let tick = 0;
  const timers = new Map(); const listeners = new Map();
  const visualViewport = { width: 320, height: visualHeight, offsetLeft: 0, offsetTop: visualTop,
    addEventListener: (name, fn) => listeners.set(`visual:${name}`, fn), removeEventListener: name => listeners.delete(`visual:${name}`) };
  const document = { activeElement: null, body: {}, documentElement: { clientWidth: 390, clientHeight: 700 },
    addEventListener: (name, fn) => listeners.set(name, fn), removeEventListener: name => listeners.delete(name) };
  const trigger = { getBoundingClientRect: () => ({ left: 100, right: 113, width: 13, height: 13, top: visualTop + 80, bottom: visualTop + 93 }),
    contains: node => node === trigger, querySelector: () => null, focus() { document.activeElement = trigger; } };
  const tip = { style: {}, scrollHeight: contentHeight, contains: node => node === tip, classList: { add() {} },
    get offsetHeight() { return Math.min(contentHeight, Number.parseFloat(this.style.maxHeight) || Infinity); },
    get clientHeight() { return this.offsetHeight; }, focus() { document.activeElement = tip; } };
  function render() {
    if (rendering) { queued = true; return; }
    rendering = true;
    do {
      queued = false; cursor = 0; tree = InfoHint({ hint: realHint });
      nodes(tree).forEach(node => { if (node.props?.ref) node.props.ref.current = node.props.role === 'tooltip' ? tip : trigger; });
      for (const slot of slots) if (slot.dirty) { slot.dirty = false; slot.cleanup?.(); slot.cleanup = slot.fn(); }
    } while (queued);
    rendering = false;
  }
  const React = {
    useState(initial) { const s = slots[cursor++] ??= { value: initial }; return [s.value, next => { const value = typeof next === 'function' ? next(s.value) : next; if (!Object.is(value, s.value)) { s.value = value; render(); } }]; },
    useRef(initial) { return slots[cursor++] ??= { current: initial }; }, useId() { return 'mobile-infohint'; },
    useCallback(fn, deps) { const s = slots[cursor++] ??= {}; if (!s.deps || deps.some((d, i) => !Object.is(d, s.deps[i]))) Object.assign(s, { value: fn, deps }); return s.value; },
    useEffect(fn, deps) { const s = slots[cursor++] ??= {}; if (!s.deps || deps.some((d, i) => !Object.is(d, s.deps[i]))) Object.assign(s, { fn, deps, dirty: true }); },
  };
  React.useLayoutEffect = React.useEffect;
  const window = { visualViewport, addEventListener: (name, fn) => listeners.set(`window:${name}`, fn), removeEventListener: name => listeners.delete(`window:${name}`),
    setTimeout(fn) { const id = ++tick; timers.set(id, fn); return id; }, clearTimeout: id => timers.delete(id) };
  const source = fs.readFileSync(new URL('../src/components/shared/InfoHint.tsx', import.meta.url), 'utf8');
  const compiled = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } }).outputText;
  const module = { exports: {} };
  vm.runInNewContext(compiled, { module, exports: module.exports, window, document,
    ResizeObserver: class { observe() {} disconnect() {} },
    require(id) {
      if (id === 'react') return React;
      if (id === 'react-dom') return { createPortal: node => node };
      if (id === 'react/jsx-runtime') return { jsx, jsxs: jsx };
      if (id === '@/lib/utils') return { cn: (...args) => args.filter(Boolean).join(' ') };
      if (id.endsWith('i18n/core.ts')) return { t: text => text };
      throw new Error(id);
    },
  });
  const InfoHint = module.exports.default;
  // 一段与真实评分说明同量级的长文案：足以触发「长说明」的滚动与视口约束路径。
  const body = '六族内在评分按权重合成：短期动量 16%、中期动量 24%、长期动量 14%、趋势结构 16%、突破质量 15%、价格行为 15%。任一族缺少数据时，其权重按比例分给其余各族。市场形态由 TOPIX 走势与市场广度六个维度给出，只在请求时叠加，不改写夜间保存的分数。';
  const realHint = { title: '强度评分（0–100）', body }; render();
  return { tree: () => tree, trigger, tip, document, listeners, visualViewport,
    button: () => nodes(tree).find(n => n.props?.role === 'button'), tooltip: () => nodes(tree).find(n => n.props?.role === 'tooltip'),
    flush() { const pending = [...timers.values()]; timers.clear(); pending.forEach(fn => fn()); },
    unmount() { slots.forEach(s => s.cleanup?.()); } };
}
const event = (extra = {}) => ({ stopPropagation() {}, preventDefault() {}, ...extra });

test('long explanation stays inside visual viewport above a keyboard and follows resize', () => {
  const h = setup({ visualTop: 120 }); h.button().props.onFocus();
  assert.equal(h.tip.style.maxHeight, '164px');
  assert.ok(Number.parseFloat(h.tip.style.top) >= 128);
  assert.ok(Number.parseFloat(h.tip.style.top) + h.tip.offsetHeight <= 292);
  assert.ok(h.tip.scrollHeight > h.tip.clientHeight);
  h.visualViewport.height = 140; h.listeners.get('visual:resize')();
  assert.equal(h.tip.style.maxHeight, '124px');
  assert.ok(Number.parseFloat(h.tip.style.top) + h.tip.offsetHeight <= 252);
  h.unmount(); assert.equal(h.listeners.has('visual:resize'), false);
});

test('keyboard enters long explanation; Escape returns focus without reopening', () => {
  const h = setup(); h.button().props.onFocus(); h.document.activeElement = h.trigger;
  h.button().props.onKeyDown(event({ key: 'ArrowDown' })); assert.equal(h.document.activeElement, h.tip);
  h.tooltip().props.onFocus(); h.tooltip().props.onKeyDown(event({ key: 'Escape' }));
  assert.equal(h.document.activeElement, h.trigger); assert.equal(h.tooltip(), undefined);
});

test('portal click does not activate parent, portal press stays open, outside press dismisses', () => {
  const h = setup(); h.button().props.onClick(event());
  h.listeners.get('pointerdown')({ target: h.tip }); assert.ok(h.tooltip());
  let stopped = 0; h.tooltip().props.onClick(event({ stopPropagation() { stopped++; } })); assert.equal(stopped, 1);
  h.listeners.get('pointerdown')({ target: {} }); assert.equal(h.tooltip(), undefined);
});

test('short hover survives trigger-to-portal gap and closes after leaving both', () => {
  const h = setup({ contentHeight: 70, visualHeight: 700 });
  h.tree().props.onMouseEnter(); h.tree().props.onMouseLeave(event({ relatedTarget: null }));
  h.tooltip().props.onMouseEnter(); h.flush(); assert.ok(h.tooltip());
  h.tooltip().props.onMouseLeave(event({ relatedTarget: null })); h.flush(); assert.equal(h.tooltip(), undefined);
});

test('second press closes a pinned explanation even while the trigger remains focused', () => {
  const h = setup(); h.button().props.onFocus();
  h.button().props.onClick(event()); assert.ok(h.tooltip());
  h.button().props.onClick(event()); assert.equal(h.tooltip(), undefined);
});
