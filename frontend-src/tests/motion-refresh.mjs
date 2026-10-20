import test from 'node:test';
import assert from 'node:assert/strict';
import { wall, projectCoast, handoff } from '../src/lib/feel.ts';

const near = (actual, expected, tolerance = 1e-8) => assert.ok(Math.abs(actual - expected) < tolerance, `${actual} != ${expected}`);

test('sheet rebound follows the damped spring trajectory and settles at its target', () => {
  let frames;
  handoff({ style: {}, animate(value) { frames = value; return {}; } }, { fromY: 40, vy: -150 });
  // Independent analytical oracle for the production sheet's 3 Hz / 0.84 damping.
  const w0 = 2 * Math.PI * 3;
  const zeta = 0.84;
  const wd = w0 * Math.sqrt(1 - zeta ** 2);
  const a = 40;
  const b = (-150 + zeta * w0 * a) / wd;
  for (const index of [0, 1, 5, 15, 30]) {
    const time = index / 60;
    const expected = Math.exp(-zeta * w0 * time) * (a * Math.cos(wd * time) + b * Math.sin(wd * time));
    const actual = Number(frames[index].transform.match(/, ([\d.-]+)px, 0/)[1]);
    near(actual, expected, 0.01);
  }
  assert.equal(frames.at(-1).transform, 'translate3d(0.00px, 0.00px, 0)');
});

test('drag walls remain continuous and release projection keeps momentum direction', () => {
  near(wall(0, 0, 14), 0);
  near(wall(14, 0, 14), 14);
  assert.ok(wall(-40, 0, 14) > -40);
  assert.ok(wall(54, 0, 14) < 54);
  assert.ok(wall(-10000, 0, 14) > -30);
  assert.ok(wall(10000, 0, 14) < 44);
  near(projectCoast(30, 0), 30);
  assert.ok(projectCoast(30, 450) > 110);
  assert.ok(projectCoast(30, -450) < 0);
});

test('animation handoff samples the compositor clock and cancellation retires the callback', () => {
  let completed = 0;
  let animation;
  const panel = {
    style: { transform: '' },
    animate(frames, options) {
      animation = { currentTime: options.duration / 2, onfinish: null, cancel() { this.cancelled = true; } };
      assert.equal(frames[0].transform, 'translate3d(0.00px, 40.00px, 0)');
      assert.equal(frames.at(-1).transform, 'translate3d(0.00px, 0.00px, 0)');
      return animation;
    },
  };
  const controller = handoff(panel, { fromY: 40, onFinish: () => completed++ });
  const sample = controller.sample();
  near(sample.t, 0.5);
  assert.ok(Number.isFinite(sample.y));
  animation.currentTime = 0;
  near(controller.sample().y, 40);
  controller.cancel();
  assert.equal(animation.onfinish, null);
  assert.equal(animation.cancelled, true);
  assert.equal(completed, 0);
});

test('reduced motion handoff snaps without scheduling an animation', () => {
  const previous = globalThis.window;
  globalThis.window = { matchMedia: () => ({ matches: true }) };
  try {
    let completed = 0;
    const panel = { style: { transform: 'translateY(40px)' }, animate() { assert.fail('unexpected motion'); } };
    const controller = handoff(panel, { fromY: 40, onFinish: () => completed++ });
    assert.equal(panel.style.transform, '');
    assert.equal(completed, 1);
    near(controller.sample().y, 0);
  } finally {
    globalThis.window = previous;
  }
});
