import test from 'node:test';
import assert from 'node:assert/strict';
import { accessIdentity } from '../src/hooks/accessIdentity.ts';

test('customer sessions determine data identity even when owner permissions remain', () => {
  const status = { mode: 'private_network', is_owner: true, password_configured: false };
  const first = accessIdentity({ ...status, account: { logged_in: true, username: 'customer-a' } });
  const second = accessIdentity({ ...status, account: { logged_in: true, username: 'customer-b' } });
  assert.equal(first, 'account:customer-a');
  assert.equal(second, 'account:customer-b');
  assert.notEqual(first, second);
  assert.equal(accessIdentity(status), 'owner');
  assert.equal(accessIdentity({ ...status, is_owner: false }), 'visitor');
  assert.equal(accessIdentity(null), 'unknown');
});
