import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';
import { dropQueryRegistry, invalidateQueryPaths, registryGet } from '../src/api/queryRegistry.ts';

function pageHandler(page, name, context) {
  const source = fs.readFileSync(new URL(`../src/pages/${page}.tsx`, import.meta.url), 'utf8');
  const parsed = ts.createSourceFile(`${page}.tsx`, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  let callback;
  function visit(node) {
    if (ts.isVariableDeclaration(node) && node.name.getText(parsed) === name) {
      callback = ts.isCallExpression(node.initializer) ? node.initializer.arguments[0] : node.initializer;
    }
    ts.forEachChild(node, visit);
  }
  visit(parsed);
  assert.ok(callback, `${page}.${name} exists`);
  return vm.runInNewContext(ts.transpile(`(${callback.getText(parsed)})`, { target: ts.ScriptTarget.ES2022 }), context);
}

test('page refresh handlers read a new response while the registered value is still fresh', async (t) => {
  let version = 1;
  let lastCache;
  t.mock.method(globalThis, 'fetch', async (_url, init) => {
    lastCache = init.cache;
    return new globalThis.Response(JSON.stringify({ version }));
  });
  const cases = [
    ['Home', 'refreshMarket', '/market/overview', 'market'],
    ['Home', 'refreshRadar', '/radar/current', 'radar'],
    ['Home', 'refreshEarnings', '/earnings/recent', 'earnings'],
    ['Market', 'refreshOverview', '/market/overview', 'refreshMarket'],
    ['DataStatus', 'refreshStatus', '/data-status', 'query'],
    ['Earnings', 'onForceRefresh', '/earnings/recent', 'recentQ'],
  ];
  for (const [page, handler, path, binding] of cases) {
    dropQueryRegistry();
    version = 1;
    await registryGet(path);
    version = 2;
    assert.equal((await registryGet(path)).version, 1, `${path} is still cached`);
    let result;
    const refresh = options => {
      assert.equal(options.force, true);
      result = registryGet(path);
    };
    const context = {
      invalidateQueryPaths,
      [binding]: binding === 'refreshMarket' ? refresh : { refresh },
      q: { refreshing: false, refresh: () => {} },
      setPendingFlash: () => {},
    };
    pageHandler(page, handler, context)();
    assert.equal((await result).version, 2, `${page}.${handler} bypasses its fresh cache`);
    assert.equal(lastCache, 'reload');
  }
  dropQueryRegistry();
});
