import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';
import { createReactStub } from './helpers/feel-react-hooks.mjs';

function harness() {
  let now = 0, id = 0;
  const frames = new Map(), listeners = new Map(), preferences = new Set();
  const media = { matches: false, addEventListener: (_, fn) => preferences.add(fn), removeEventListener: (_, fn) => preferences.delete(fn) };
  const react = createReactStub(); react.React.useLayoutEffect = react.React.useEffect;
  const module = { exports: {} };
  const source = ts.transpileModule(fs.readFileSync(new URL('../src/lib/feel.ts', import.meta.url), 'utf8'), { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS } }).outputText;
  vm.runInNewContext(source, { module, exports: module.exports, require: () => react.React,
    window: { matchMedia: () => media, addEventListener: (name, fn) => listeners.set(name, fn), removeEventListener: (name) => listeners.delete(name) },
    performance: { now: () => now }, requestAnimationFrame: fn => { frames.set(++id, fn); return id; }, cancelAnimationFrame: n => frames.delete(n),
  });
  const style = new Map(), captures = new Set();
  const button = { dataset: {}, style: { setProperty: (k,v) => style.set(k,v) }, setPointerCapture: n => captures.add(n), hasPointerCapture: n => captures.has(n), releasePointerCapture: n => captures.delete(n) };
  let checked = false, disabled = false, changes = 0, api;
  const render = () => { api = module.exports.useFeelToggleDrag({ checked, disabled, onToggle: () => { checked = !checked; changes++; react.rerender(); } }); api.attach(button); return api; };
  react.mount(render);
  const pointer = (method, x, pointerId = 1) => api[method]({ pointerId, button: 0, isPrimary: true, clientX: x, currentTarget: button });
  const advance = (ms) => { for (let elapsed = 0; elapsed < ms; elapsed += 4) { now += 4; const batch = [...frames.values()]; frames.clear(); batch.forEach(fn => fn(now)); } };
  return { model: module.exports.HeavyToggleMotion, pointer, advance, style, media, frames, button,
    get api() { return api; }, get checked() { return checked; }, get changes() { return changes; },
    reduce() { media.matches = true; preferences.forEach(fn => fn()); }, blur() { listeners.get('blur')?.(); },
    disable() { disabled = true; react.rerender(); }, unmount: react.unmount,
  };
}

test('hand spring lags; release preserves body state and uses its momentum', () => {
  const h = harness(), motion = new h.model(14, false);
  motion.pull(14); motion.body.step(0.016);
  assert.ok(motion.body.x > 0 && motion.body.x < 14);
  const x = motion.body.x, v = motion.body.v;
  assert.ok(v > 0);
  const expected = x + v * motion.spring.mass / motion.spring.damping > 7;
  assert.equal(motion.release(), expected);
  assert.equal(motion.body.x, x); assert.equal(motion.body.v, v);
  for (let i=0; i<500; i++) motion.body.step(1/240);
  assert.ok(Math.abs(motion.body.x - (expected ? 14 : 0)) < 0.001);
});


test('coast prediction uses the released spring damping, not an arbitrary drag coefficient', () => {
  const h = harness(), motion = new h.model(14, false);
  assert.equal(motion.hand.stiffness, (2 * Math.PI * 6) ** 2);
  assert.ok(motion.hand.damping > motion.spring.damping);
  motion.body.set(4, 50);
  assert.equal(motion.release(), false, 'short slow pull stays off');
  motion.body.set(4, 200);
  assert.equal(motion.release(), true, 'sufficient body momentum crosses the midpoint');
});

test('stopping the hand lets body momentum decay before the release decision', () => {
  const h = harness(), motion = new h.model(14, false);
  motion.pull(4);
  for (let i=0; i<500; i++) motion.body.step(1/240);
  assert.equal(motion.release(), false);
});

test('drag retains physical location through release and suppresses its synthetic click', () => {
  const h = harness(); h.pointer('onPointerDown', 0); h.pointer('onPointerMove', 14); h.advance(200);
  const before = Number.parseFloat(h.style.get('--thumb-physical-x'));
  assert.ok(before > 0 && before < 14);
  h.pointer('onPointerUp', 14);
  assert.equal(Number.parseFloat(h.style.get('--thumb-physical-x')), before);
  assert.equal(h.checked, true); assert.equal(h.api.consumeSuppressedClick(1), true);
  h.advance(1500); assert.ok(Math.abs(Number.parseFloat(h.style.get('--thumb-physical-x'))-14)<0.01);
  assert.equal(h.style.get('--toggle-fill'), '1');
});

test('cancel, capture loss, blur, disable, preference change and unmount stop active motion', () => {
  for (const action of ['onPointerCancel', 'onLostPointerCapture', 'blur', 'disable', 'reduce', 'unmount']) {
    const h = harness(); h.pointer('onPointerDown', 0); h.pointer('onPointerMove', 14); h.advance(24);
    if (action.startsWith('on')) h.pointer(action, 14); else h[action]();
    assert.equal(h.frames.size, 0, action); assert.equal(h.changes, 0, action);
    assert.equal(h.button.dataset.feelDrag, undefined, action);
    if (action !== 'unmount') assert.equal(h.style.get('--thumb-physical-x'), '0px', action);
  }
});

test('reduced motion, arrows and native click activation keep semantic state', () => {
  const h = harness(); h.reduce();
  h.api.activate(); assert.equal(h.checked, true); assert.equal(h.style.get('--thumb-physical-x'), '14px');
  h.api.onKeyDown({ key: 'ArrowLeft', preventDefault() {}, stopPropagation() {} });
  assert.equal(h.checked, false); assert.equal(h.frames.size, 0);
  h.pointer('onPointerDown', 0); h.pointer('onPointerMove', 14); h.pointer('onPointerUp', 14);
  assert.equal(h.checked, true); assert.equal(h.style.get('--thumb-scale-x'), '1');
  assert.equal(h.api.consumeSuppressedClick(0), false);
});

test('a final pointerup displacement is integrated in normal and reduced motion', () => {
  for (const reduced of [false, true]) {
    const h = harness();
    if (reduced) h.reduce();
    h.pointer('onPointerDown', 0);
    h.advance(120);
    h.pointer('onPointerUp', 15);
    assert.equal(h.checked, true, `reduced=${reduced}`);
    assert.equal(h.changes, 1);
    assert.equal(h.api.consumeSuppressedClick(1), true);
    h.advance(1500);
    assert.equal(h.style.get('--toggle-fill'), '1');
  }
});
