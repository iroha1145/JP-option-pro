/**
 * 後端が返す説明文（テンプレート + パラメータ）を訳せているか。
 *
 * 「テンプレートを t() に通す」だけでは足りない場面が 2 つあり、どちらも
 * 一度は本番で中文が漏れた:
 *
 *   1. **パラメータ自身が訳語を持つ** —— 「当前被分类为『{label}』」の label は
 *      「卖压吸收」で、辞書に載っている。訳さないと文の中だけ中文で残る。
 *   2. **列挙は結合前に訳す** —— 「3家减仓、1家跌破门槛」は結合済みなので
 *      辞書のどのキーにも当たらない。1 項目ずつ訳して、区切りも言語で選ぶ。
 *
 * pytest 側の門（`tests/test_backend_text_is_translatable.py`）は「辞書に
 * 載っているか」を見る。こちらは **載っているものを正しく引けているか**。
 * 別々に壊れるので、門も別にする。
 *
 * 言語は `i18n/core` の読み込み時に確定する（切り替え = 整頁リロード）ので、
 * 言語ごとに **プロセスを分ける**。引数なしで起動すると 3 言語ぶん自分を
 * 呼び直す。
 *
 * 実行: node --experimental-strip-types frontend-src/tests/explain_text.mjs
 */
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { registerHooks } from 'node:module';

const LOCALES = ['zh', 'en', 'ja'];
const locale = process.env.OPTIX_TEST_LOCALE;

if (!locale) {
  let failed = 0;
  for (const each of LOCALES) {
    const result = spawnSync(process.execPath, [...process.execArgv, ...process.argv.slice(1)], {
      stdio: 'inherit',
      env: { ...process.env, OPTIX_TEST_LOCALE: each },
    });
    if (result.status !== 0) failed += 1;
  }
  process.exit(failed ? 1 : 0);
}

// `@/…` は Vite のエイリアス。node は知らないので、ここで src/ に読み替える。
const SRC = new URL('../src/', import.meta.url);
registerHooks({
  resolve(specifier, context, nextResolve) {
    if (!specifier.startsWith('@/')) return nextResolve(specifier, context);
    const rest = specifier.slice(2);
    const target = new URL(/\.[a-z]+$/.test(rest) ? rest : `${rest}.ts`, SRC);
    return nextResolve(target.href, context);
  },
});

// core は読み込み時に localStorage を見て言語を決める。window が無い Node では
// 既定が 'zh' になるので、import より **先に** 差し込む。
globalThis.localStorage = {
  getItem: (key) => (key === 'optixjp:locale' ? locale : null),
  setItem: () => {},
};

const { getLocale, t } = await import('../src/i18n/core.ts');
const { explanationLine, explanationLines } = await import('../src/lib/explainText.ts');

assert.equal(getLocale(), locale, `言語の差し込みに失敗（${getLocale()}）`);

let failures = 0;
function check(name, fn) {
  try {
    fn();
  } catch (error) {
    failures += 1;
    console.error(`  FAIL [${locale}] ${name}\n       ${error.message}`);
  }
}

/** zh は msgid をそのまま返す言語。訳文の中身は en/ja でだけ確かめる。 */
const expected = {
  zh: { tailwind: '順風', earnings: '決算', weekly: '週次' },
  en: { tailwind: 'Tailwind', earnings: 'Earnings', weekly: 'weekly' },
  ja: { tailwind: '順風', earnings: '決算', weekly: '週次' },
}[locale];

check('辞書が引ける', () => {
  assert.equal(t('順風'), expected.tailwind);
  assert.equal(t('決算'), expected.earnings);
  assert.equal(t('週次'), expected.weekly);
});

check('数値入りテンプレートは置換後も訳せる', () => {
  const line = t('ATR约{atr}%，波动风险高', { atr: '7.3' });
  assert.ok(line.includes('7.3'), line);
  assert.ok(!line.includes('{atr}'), `未置換: ${line}`);
  if (locale === 'en') assert.equal(line, 'ATR around 7.3% — high volatility risk');
  if (locale === 'ja') assert.equal(line, 'ATR は約7.3%。変動リスクが高いです');
});

check('パラメータが訳語を持つときは値も訳す', () => {
  const line = explanationLine({
    template: '当前被分类为「{label}」，数据置信度 {confidence}。该结果是模型分类，不代表机构意图。',
    params: { label: '卖压吸收', confidence: '0.50' },
  });
  assert.ok(line.includes('0.50'), line);
  assert.ok(!line.includes('{label}'), `未置換: ${line}`);
  // 訳語を持つ言語では、文の中に中文の label が残っていてはいけない。
  if (locale !== 'zh') assert.ok(!line.includes('卖压吸收'), `label が中文のまま: ${line}`);
  if (locale === 'en') assert.ok(line.includes('Absorption'), line);
  if (locale === 'ja') assert.ok(line.includes('売り圧の吸収'), line);
});

check('列挙は結合前に訳し、区切りも辞書から取る', () => {
  const line = explanationLine({
    template: '过去 20 个交易日：{moves}。',
    params: {},
    parts: [
      { template: '{n}家减仓', params: { n: 3 } },
      { template: '{n}家跌破门槛', params: { n: 1 } },
    ],
  });
  assert.ok(!line.includes('{moves}'), `moves が埋まっていない: ${line}`);
  assert.ok(line.includes('3') && line.includes('1'), line);
  if (locale !== 'zh') assert.ok(!line.includes('家减仓'), `列挙が中文のまま: ${line}`);
  // 英語の区切りはカンマ + 半角空白（読点ではない）。
  if (locale === 'en') assert.ok(line.includes(', '), line);
});

check('parts_key / parts_sep を指定した列挙（ニュースのイベント種別）', () => {
  const line = explanationLine({
    template: '事件类别: {categories}',
    params: {},
    parts: [{ template: '決算' }, { template: '配当' }],
    parts_key: 'categories',
    parts_sep: '/',
  });
  assert.ok(!line.includes('{categories}'), `categories が埋まっていない: ${line}`);
  assert.ok(line.includes('/'), `区切りが落ちている: ${line}`);
  if (locale === 'en') assert.equal(line, 'Event type: Earnings/Dividend');
  if (locale === 'ja') assert.equal(line, 'イベント種別: 決算/配当');
});

check('items が無ければ旧フィールド（置換済みの文）に落ちる', () => {
  assert.deepEqual(explanationLines(null, []), []);
  const fallback = explanationLines(undefined, ['长期趋势仍未修复']);
  assert.equal(fallback.length, 1);
  if (locale === 'en') assert.equal(fallback[0], 'Long-term trend not yet repaired');
});

check('items があれば旧フィールドは見ない', () => {
  const out = explanationLines([{ template: '关联上市公司' }], ['これは使われない']);
  assert.equal(out.length, 1);
  assert.ok(!out[0].includes('使われない'), out[0]);
  if (locale === 'en') assert.equal(out[0], 'Linked to listed companies');
});

if (failures) {
  console.error(`explain_text [${locale}]: ${failures} 件失敗`);
  process.exit(1);
}
console.log(`explain_text [${locale}] ok`);
