import test from 'node:test';
import assert from 'node:assert/strict';
import { cn } from '../src/lib/utils.ts';
import { NAV_GROUPS, isNavGroupActive, navAriaCurrent } from '../src/lib/navigation.ts';

test('custom text sizes survive semantic color merging', () => {
  for (const size of ['tag', 'micro', 'caption', 'body-s', 'h3', 'display-l', 'data-xl']) {
    assert.equal(cn(`text-${size}`, 'text-ink-400'), `text-${size} text-ink-400`);
  }
  assert.equal(cn('text-micro', 'text-caption', 'text-ink-400'), 'text-caption text-ink-400');
});

test('Japan navigation keeps child pages active without prefix collisions', () => {
  const screen = NAV_GROUPS.find(group => group.section === 'screener');
  const market = NAV_GROUPS.find(group => group.section === 'market');
  assert.ok(screen);
  assert.ok(market);
  assert.equal(isNavGroupActive('/radar', screen), true);
  assert.equal(navAriaCurrent('/radar', screen), 'true');
  assert.equal(navAriaCurrent('/screener', screen), 'page');
  assert.equal(isNavGroupActive('/radar-old', screen), false);
  assert.equal(isNavGroupActive('/short-monitor', market), true);
  assert.equal(isNavGroupActive('/research', market), false);
});
