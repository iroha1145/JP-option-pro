/**
 * 気配の出所ラベル。**画面にベンダ名や「15分」を焼き込まない**ための一枚。
 *
 * これまで各ページが `延迟{n}分 · 非官方源` を直接書いていたので、将来
 * 証券端末のリアルタイムが繋がっても「15分遅延・非公式」と言い続ける。
 * サーバが申告する delay_class / is_official / delayed_minutes から作る。
 */

import type { QuoteSourceEnvelope } from '@/api/types';
import { t } from '@/i18n/core';

export type SourceTone = 'warn' | 'ok';

export interface QuoteSourceLabel {
  /** 表示文字列（翻訳済み） */
  text: string;
  /** 非公式・遅延なら warn、公式リアルタイムなら ok */
  tone: SourceTone;
}

export function quoteSourceLabel(
  envelope: QuoteSourceEnvelope | null | undefined,
): QuoteSourceLabel {
  const minutes = envelope?.delayed_minutes ?? 15;
  const realtime = envelope?.is_realtime ?? envelope?.delay_class === 'realtime';
  const official = envelope?.is_official ?? false;

  if (realtime && official) return { text: t('实时 · 官方源'), tone: 'ok' };
  if (realtime) return { text: t('实时 · 非官方源'), tone: 'warn' };
  if (official) return { text: t('延迟{n}分 · 官方源', { n: minutes }), tone: 'warn' };
  return { text: t('延迟{n}分 · 非官方源', { n: minutes }), tone: 'warn' };
}
