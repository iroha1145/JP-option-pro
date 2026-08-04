/**
 * 後端が組み立てた説明文（中文テンプレート + パラメータ）を今の言語で描画する。
 *
 * テンプレートを `t()` に通すだけでは足りない —— **パラメータ自身が訳語を
 * 持つ文字列のことがある**。
 *
 *   「当前被分类为『{label}』…」 の label = 「卖压吸收」
 *   「过去 20 个交易日：{moves}。」 の moves = 「3家减仓、1家跌破门槛」
 *
 * 前者は辞書に載っているので値も訳す。後者は結合済みの文字列で辞書に載らない
 * ので、後端が一緒に返す `parts`（1 項目 = 1 テンプレート）から組み直す。
 * 区切り記号も言語で違うので辞書引きにする。
 *
 * 数値や「1.98%」のような値は辞書に無いため素通しになる（`hasTranslation`
 * で先に確かめるので、開発時の「訳が無い」警告も出さない）。
 */
import { hasTranslation, t } from '@/i18n/core';

export interface ExplanationItem {
  template: string;
  params?: Record<string, string | number>;
  /** 「A、B、C」のような列挙。結合前の 1 項目ずつ。 */
  parts?: { template: string; params?: Record<string, string | number> }[];
}

export function explanationLine(item: ExplanationItem): string {
  const params: Record<string, string | number> = {};
  for (const [key, value] of Object.entries(item.params ?? {})) {
    params[key] = typeof value === 'string' && hasTranslation(value) ? t(value) : value;
  }
  if (item.parts?.length) {
    params.moves = item.parts
      .map((part) => t(part.template, part.params))
      .join(t('、'));
  }
  return t(item.template, params);
}
