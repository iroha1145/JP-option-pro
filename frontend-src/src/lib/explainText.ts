/**
 * 後端が組み立てた説明文（テンプレート + パラメータ）を今の言語で描画する。
 *
 * サーバは相手の言語を知らない（応答は ETag で共有される）ので、完成した文では
 * なくテンプレートを返してくる。ここがその置換係。後端側の約束は
 * `backend/app/services/display_text.py` にある。
 *
 * テンプレートを `t()` に通すだけでは足りない —— **パラメータ自身が訳語を
 * 持つ文字列のことがある**。
 *
 *   「当前被分类为『{label}』…」   の label = 「卖压吸收」
 *   「过去 20 个交易日：{moves}。」 の moves = 「3家减仓、1家跌破门槛」
 *   「事件类别: {categories}」      の categories = 「決算/配当」
 *
 * 前者は辞書に載っているので値も訳す。後の 2 つは結合済みの文字列で辞書に
 * 載らないので、後端が一緒に返す `parts`（1 項目 = 1 テンプレート）から
 * 組み直す。区切り記号も言語で違うので辞書引きにする。
 *
 * 数値や「1.98%」のような値は辞書に無いため素通しになる（`hasTranslation`
 * で先に確かめるので、開発時の「訳が無い」警告も出さない）。
 */
import type { ExplanationItem } from '@/api/types';
import { hasTranslation, t } from '@/i18n/core';

export type { ExplanationItem };

export function explanationLine(item: ExplanationItem): string {
  const params: Record<string, string | number> = {};
  for (const [key, value] of Object.entries(item.params ?? {})) {
    params[key] = typeof value === 'string' && hasTranslation(value) ? t(value) : value;
  }
  if (item.parts?.length) {
    const separator = item.parts_sep ?? '、';
    params[item.parts_key ?? 'moves'] = item.parts
      .map(explanationLine)
      .join(hasTranslation(separator) ? t(separator) : separator);
  }
  return t(item.template, params);
}

/**
 * `*_items`（テンプレート形）があればそれを訳す。無ければ **中文で置換済みの
 * 旧フィールド** に落ちる —— 後端がまだ古い間だけ通る道。素の文もパラメータの
 * 無いものは msgid そのものなので、一応 `t()` を通しておく。
 */
export function explanationLines(
  items: ExplanationItem[] | null | undefined,
  fallback: readonly string[] = [],
): string[] {
  if (items?.length) return items.map(explanationLine);
  return fallback.map((line) => t(line));
}
