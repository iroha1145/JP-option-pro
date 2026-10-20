import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { setImmediate } from 'node:timers';
import ts from 'typescript';

// Execute the page's search effect with controlled network completion and timers.
const source = fs.readFileSync(process.env.WATCHLIST_SOURCE ?? new URL('../src/pages/Watchlist.tsx', import.meta.url), 'utf8');
const parsed = ts.createSourceFile('Watchlist.tsx', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
const form = parsed.statements.find(node => ts.isFunctionDeclaration(node) && node.name?.text === 'AddStockForm');
const effectStatement = form.body.statements.find(node =>
  ts.isExpressionStatement(node) && ts.isCallExpression(node.expression) && node.expression.expression.getText(parsed) === 'useEffect');
const effectCode = ts.transpile(`(${effectStatement.expression.arguments[0].getText(parsed)})`, { target: ts.ScriptTarget.ES2022 });

function searchHarness() {
  const timers = new Map();
  const requests = [];
  const state = { suggestions: [], open: false };
  const context = vm.createContext({
    input: '',
    seqRef: { current: 0 },
    setSuggestions: value => { state.suggestions = value; },
    setOpen: value => { state.open = value; },
    window: {
      setTimeout: callback => { const id = Symbol(); timers.set(id, callback); return id; },
      clearTimeout: id => timers.delete(id),
    },
    stocksApi: {
      search: keyword => new Promise(resolve => requests.push({ keyword, resolve })),
    },
  });
  const effect = vm.runInContext(effectCode, context);
  let cleanup;
  return {
    state,
    requests,
    change(input) { cleanup?.(); context.input = input; cleanup = effect(); },
    send() { for (const callback of timers.values()) callback(); timers.clear(); },
    unmount() { cleanup?.(); },
    async finish(index, code) {
      requests[index].resolve({ results: [{ canonical_code: code }] });
      await new Promise(resolve => setImmediate(resolve));
    },
  };
}

test('shortened input cannot be repopulated by an earlier search', async () => {
  const h = searchHarness();
  h.change('7203');
  h.send();
  h.change('7');
  await h.finish(0, '7203');
  assert.equal(h.state.suggestions.length, 0);
  assert.equal(h.state.open, false);
});

test('new input clears old choices and only its own response can reopen the list', async () => {
  const h = searchHarness();
  h.change('7203');
  h.send();
  await h.finish(0, '7203');
  assert.equal(h.state.open, true);
  h.change('6758');
  assert.equal(h.state.suggestions.length, 0);
  assert.equal(h.state.open, false);
  h.send();
  h.change('9984');
  h.send();
  await h.finish(2, '9984');
  await h.finish(1, '6758');
  assert.equal(h.state.suggestions[0].canonical_code, '9984');
});

test('unmount cancels pending timers and ignores an in-flight response', async () => {
  const h = searchHarness();
  h.change('7203');
  h.unmount();
  h.send();
  assert.equal(h.requests.length, 0);
  h.change('6758');
  h.send();
  h.unmount();
  await h.finish(0, '6758');
  assert.equal(h.state.suggestions.length, 0);
  assert.equal(h.state.open, false);
});
