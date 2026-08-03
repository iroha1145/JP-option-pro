/* 辞書の重複キー検出。
 *
 * 既存エントリの多くは **クオート無し** のキー（`加载中:`）で書かれていて、
 * `grep "'加载中'"` では見つからない。実際にこれで重複を 2 件作った。
 * tsc も TS1117 で捕まえるが、ここでは理由の分かるメッセージを出す。 */

import { readFileSync } from 'node:fs';

const file = new URL('../src/i18n/dict/index.ts', import.meta.url);
const lines = readFileSync(file, 'utf8').split('\n');
const pattern = /^\s*(?:'((?:[^'\\]|\\.)*)'|([^\s:'"][^:]*?))\s*:\s*\[/;

const seen = new Map();
const duplicates = [];
lines.forEach((line, index) => {
  const match = pattern.exec(line);
  if (!match) return;
  const key = (match[1] ?? match[2]).trim();
  if (seen.has(key)) duplicates.push({ key, first: seen.get(key), again: index + 1 });
  else seen.set(key, index + 1);
});

if (duplicates.length > 0) {
  for (const d of duplicates) {
    console.error(`duplicate dict key ${JSON.stringify(d.key)}: line ${d.first} and line ${d.again}`);
  }
  process.exit(1);
}
console.log(`dict ok: ${seen.size} keys, no duplicates`);
