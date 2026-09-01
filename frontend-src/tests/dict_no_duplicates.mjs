/* 辞書の重複キー検出。
 *
 * 既存エントリの多くは **クオート無し** のキー（`加载中:`）で書かれていて、
 * `grep "'加载中'"` では見つからない。実際にこれで重複を 2 件作った。
 * tsc も TS1117 で捕まえるが、ここでは理由の分かるメッセージを出す。
 *
 * 長いキーは `[` が **次の行に折り返す**:
 *
 *     'とても長い msgid':
 *       ['English', '日本語'],
 *
 * 同じ行に `[` を求めると、この形が丸ごと見えない —— 見えないキーは
 * 重複していても素通しになる。数え落としに気づけるよう、最後に
 * 実際のキー数（DICT を読み込んだ結果）と突き合わせる。 */

import { readFileSync } from 'node:fs';

const file = new URL('../src/i18n/dict/index.ts', import.meta.url);
const lines = readFileSync(file, 'utf8').split('\n');
// キーは同じ行で完結させる（`[^:'"]` は改行に当たらないので行単位で見る）。
// 先頭に `*` `/` を許さない —— 許すとコメント行がキーとして拾われる。
const pattern = /^\s*(?:'((?:[^'\\]|\\.)*)'|([^\s:'"*/][^:'"]*?))\s*:\s*(\[|$)/;

const seen = new Map();
const duplicates = [];
lines.forEach((line, index) => {
  const match = pattern.exec(line);
  if (!match) return;
  // `[` が無い行は、次の非空行が `[` で始まるときだけエントリと見なす。
  if (!match[3]) {
    const next = lines.slice(index + 1).find((l) => l.trim() !== '');
    if (!next?.trimStart().startsWith('[')) return;
  }
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

// 数え落としの見張り。この走査が実物より少なければ、見えていないキーがある
// —— そこに重複があっても、この門は静かに通してしまう。
const { DICT } = await import('../src/i18n/dict/index.ts');
const actual = Object.keys(DICT).length;
if (seen.size !== actual) {
  console.error(
    `dict scan missed ${actual - seen.size} key(s): scanned ${seen.size}, DICT has ${actual}. ` +
      'この差ぶんは重複検査が効いていない。上の pattern を直すこと。',
  );
  process.exit(1);
}
console.log(`dict ok: ${seen.size} keys, no duplicates`);
