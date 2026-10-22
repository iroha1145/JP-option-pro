import test from 'node:test';
import assert from 'node:assert/strict';
import { MagneticSheetBody } from '../src/lib/magneticSheet.ts';

test('a released sheet is caught by the nearby open or closed magnet', () => {
  assert.equal(new MagneticSheetBody(600, 100).path().rest, 0);
  assert.equal(new MagneticSheetBody(600, 500).path().rest, 600);
});

test('the same release position can reach different stops with different momentum', () => {
  assert.equal(new MagneticSheetBody(600, 230, 0).path().rest, 0);
  assert.equal(new MagneticSheetBody(600, 230, 3000).path().rest, 600);
});

test('a hand spring pulls the sheet without teleporting it to the pointer', () => {
  const body = new MagneticSheetBody(600);
  body.hand = { x: 200, v: 0 };
  body.step(1 / 60);
  assert.ok(body.x > 0 && body.x < 200);
  assert.ok(body.v > 0);
  const state = { x: body.x, v: body.v };
  body.hand = null;
  assert.deepEqual(body.path().samples[0], state, 'release keeps the real position and velocity');
});

test('walls oppose overshoot and the trajectory settles at a valid stop', () => {
  const body = new MagneticSheetBody(600, -40, -300);
  assert.ok(body.force(-40, -300) > 0);
  assert.ok(body.force(640, 300) < 0);
  const path = body.path();
  assert.deepEqual(path.samples.at(-1), { x: 0, v: 0 });
  assert.ok(path.samples.every(({ x, v }) => Number.isFinite(x) && Number.isFinite(v)));
  assert.ok(path.duration > 0 && path.duration < 12_000);
});

test('keyboard impulses settle at the requested stop and path duration is measured', () => {
  for (const height of [240, 788]) {
    const body = new MagneticSheetBody(height);
    body.kickTo(height);
    const closed = body.path();
    assert.equal(closed.rest, height);
    const opening = new MagneticSheetBody(height, height);
    opening.kickTo(0);
    assert.equal(opening.path().rest, 0);
    assert.equal(closed.duration, (closed.samples.length - 1) * 1000 / 120);
  }
});


test('commanded closing crosses different sheet heights promptly without a large overshoot', () => {
  for (const height of [240, 347, 400, 788]) {
    const body = new MagneticSheetBody(height);
    body.kickTo(height);
    const path = body.path();
    const nearClosed = path.samples.findIndex(sample => sample.x >= height * 0.95) / 120;
    // Behavioral budgets, not forced animation durations: the old minimum
    // impulse took roughly a second to traverse the panel at these heights.
    assert.ok(nearClosed > 0 && nearClosed < 0.25, `${height}px reaches 95% in ${nearClosed}s`);
    assert.ok(path.duration < 650, `${height}px settles in ${path.duration}ms`);
    assert.ok(Math.max(...path.samples.map(sample => sample.x)) - height < 5, `${height}px has restrained overshoot`);
    assert.equal(path.rest, height);
  }
});

test('a reverse command catches a moving sheet at the requested open stop', () => {
  for (const height of [240, 347, 400, 788]) {
    const body = new MagneticSheetBody(height);
    body.kickTo(height);
    for (let frame = 0; frame < 8; frame++) body.step(1 / 120);
    const position = body.x;
    assert.ok(position > 0 && position < height);
    body.kickTo(0);
    assert.equal(body.x, position, 'command changes momentum without teleporting the sheet');
    const path = body.path();
    assert.equal(path.rest, 0);
    assert.ok(path.duration < 1000);
    assert.ok(Math.min(...path.samples.map(sample => sample.x)) > -5);
  }
});

test('free release trajectories preserve the actual signed velocity without a command boost', () => {
  for (const velocity of [-1800, -500, 0, 500, 1800]) {
    const body = new MagneticSheetBody(600, 300, velocity);
    const path = body.path();
    assert.deepEqual(path.samples[0], { x: 300, v: velocity });
    assert.equal(body.v, velocity, 'path samples a ghost without replacing release momentum');
    if (velocity > 0) assert.equal(path.rest, 600);
    if (velocity < 0) assert.equal(path.rest, 0);
  }
});


test('commands inside either magnetic basin still cover the remaining distance promptly', () => {
  for (const height of [240, 347, 400, 788]) for (const fraction of [0.1, 0.3, 0.5, 0.7, 0.9]) for (const stop of [0, height]) {
    const body = new MagneticSheetBody(height, height * fraction);
    body.kickTo(stop);
    const path = body.path();
    assert.equal(path.rest, stop);
    assert.ok(path.duration < 650, `${height}px from ${fraction} to ${stop}: ${path.duration}ms`);
    assert.ok(path.samples.every(sample => sample.x > -5 && sample.x < height + 5));
  }
});

import { sheetHarness } from './helpers/feel-sheet-harness.mjs';

test('commanded close and backdrop share one timeline and close only after physical arrival', () => {
  const h = sheetHarness(); h.api.requestClose();
  const [panel, backdrop] = h.animations;
  assert.equal(h.closed, 0);
  assert.equal(panel.startTime, backdrop.startTime);
  assert.equal(panel.options.duration, backdrop.options.duration);
  assert.equal(panel.keyframes.length, backdrop.keyframes.length);
  panel.keyframes.forEach((frame, index) => {
    const y = Number(frame.transform.match(/, ([\d.e+-]+)px/)[1]);
    assert.equal(backdrop.keyframes[index].opacity, 1-Math.max(0,Math.min(1,y/600)));
  });
  panel.finish();
  assert.equal(h.closed, 1);
  assert.equal(h.panel.dataset.feelDismissed, 'true');
  assert.equal(h.backdrop.style.opacity, '0');
  assert.ok(panel.cancelled && backdrop.cancelled);
});

test('regrabbing a closing sheet without moving preserves release physics and consumes the native click', () => {
  const h = sheetHarness(); h.api.requestClose();
  const first = h.animations[0]; first.currentTime = first.options.duration * 0.1;
  h.pointer('onPointerDown', 10);
  assert.equal(first.cancelled, true);
  const grabbed = h.panel.style.transform;
  h.pointer('onPointerUp', 10);
  assert.equal(h.animations.length, 4, 'release resumes a physical trajectory');
  assert.equal(h.animations[2].keyframes[0].transform, grabbed, 'position is continuous');
  h.api.onClick({ detail: 1 });
  assert.equal(h.animations.length, 4, 'native click must not inject a new closing impulse');
  assert.equal(h.captures.size, 0);
});

test('cancellation, capture loss, blur, resize, disable and unmount retire gestures and callbacks', () => {
  for (const action of ['onPointerCancel','onLostPointerCapture','blur','resize','disable','unmount']) {
    const h=sheetHarness(); h.api.requestClose(); const first=h.animations[0]; first.currentTime=30;
    h.pointer('onPointerDown',0); h.pointer('onPointerMove',80); h.advance(20);
    if (action.startsWith('on')) h.pointer(action,80); else h[action]();
    assert.equal(h.frames.size,0,action); assert.equal(h.captures.size,0,action);
    assert.equal(first.onfinish,null,action); assert.equal(h.closed,0,action);
    assert.equal(h.panel.style.transform,'',action); assert.equal(h.backdrop.style.opacity,'',action);
    if (action === 'unmount') { assert.equal(h.listeners.size,0); assert.equal(h.preferences.size,0); }
    else { h.api.onClick({ detail: 1 }); assert.equal(h.animations.length,2,action); }
  }
});

test('reduced motion snaps commanded closure and removes active compositor effects', () => {
  const h=sheetHarness(); h.reduce(); h.api.requestClose();
  assert.equal(h.closed,1); assert.equal(h.animations.length,0);
  const moving=sheetHarness(); moving.api.requestClose();
  moving.animations[0].currentTime=moving.animations[0].options.duration*0.8;
  moving.reduce(); assert.equal(moving.closed,1);
  assert.ok(moving.animations.every(a=>a.cancelled));
});

test('final pointerup displacement is included and drag release does not inject a command impulse', () => {
  const h=sheetHarness(); h.pointer('onPointerDown',0); h.advance(120); h.pointer('onPointerUp',400);
  assert.equal(h.animations.length,2);
  const start=Number(h.animations[0].keyframes[0].transform.match(/, ([\d.e+-]+)px/)[1]);
  assert.ok(start>0 && start<400);
  const count=h.animations.length; h.api.onClick({detail:1}); assert.equal(h.animations.length,count);
});
