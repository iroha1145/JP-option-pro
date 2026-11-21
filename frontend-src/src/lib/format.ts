/**
 * 数値・日付フォーマット（日本市場版）。
 *
 * - タイムゾーンは常に Asia/Tokyo。閲覧者のローカル時刻でデータ日付を
 *   ずらさない（旧プロジェクトの ET バグの教訓）。
 * - 円金額は整数表示が基本、大きい値は 万 / 億 / 兆 に圧縮。
 * - 欠損は常に '—'。0 と欠損を混同しない。
 * - マイナスは U+2212 を使う（ハイフンより判読しやすい）。
 */

import { getLocale, localeTag, t } from '@/i18n/core';

const MINUS = '−';

const JA_INT_FMT = new Intl.NumberFormat('ja-JP', { maximumFractionDigits: 0 });
const ZH_INT_FMT = new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 0 });
const EN_INT_FMT = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 });
const PRICE_1_FMT = new Intl.NumberFormat('ja-JP', { minimumFractionDigits: 1, maximumFractionDigits: 1 });
const PRICE_FMT_CACHE = new Map<number, Intl.NumberFormat>([
  [0, JA_INT_FMT],
  [1, PRICE_1_FMT],
]);

function priceFormat(digits: number): Intl.NumberFormat {
  let fmt = PRICE_FMT_CACHE.get(digits);
  if (!fmt) {
    fmt = new Intl.NumberFormat('ja-JP', {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    });
    PRICE_FMT_CACHE.set(digits, fmt);
  }
  return fmt;
}

export function fmtPrice(value: number | null | undefined, digits?: number): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—';
  const resolved = digits ?? (Math.abs(value) < 100 ? 1 : 0);
  return priceFormat(resolved).format(value);
}

/** 円金額の圧縮表示（言語別の単位: ja=兆/億/万, zh=万亿/亿/万, en=¥T/B/M/K）。 */
export function fmtYenCompact(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—';
  const abs = Math.abs(value);
  const sign = value < 0 ? MINUS : '';
  const locale = getLocale();
  if (locale === 'en') {
    if (abs >= 1e12) return `${sign}¥${(abs / 1e12).toFixed(digits)}T`;
    if (abs >= 1e9) return `${sign}¥${(abs / 1e9).toFixed(digits)}B`;
    if (abs >= 1e6) return `${sign}¥${(abs / 1e6).toFixed(digits)}M`;
    if (abs >= 1e3) return `${sign}¥${(abs / 1e3).toFixed(0)}K`;
    return `${sign}¥${EN_INT_FMT.format(abs)}`;
  }
  const CHO = 1_0000_0000_0000;
  const OKU = 1_0000_0000;
  const MAN = 1_0000;
  if (locale === 'zh') {
    if (abs >= CHO) return `${sign}${(abs / CHO).toFixed(digits)}万亿`;
    if (abs >= OKU) return `${sign}${(abs / OKU).toFixed(digits)}亿`;
    if (abs >= MAN) return `${sign}${(abs / MAN).toFixed(0)}万`;
    return `${sign}${ZH_INT_FMT.format(abs)}`;
  }
  if (abs >= CHO) return `${sign}${(abs / CHO).toFixed(digits)}兆`;
  if (abs >= OKU) return `${sign}${(abs / OKU).toFixed(digits)}億`;
  if (abs >= MAN) return `${sign}${(abs / MAN).toFixed(0)}万`;
  return `${sign}${JA_INT_FMT.format(abs)}`;
}

/** 株数の圧縮表示（信用残・歩み値集計など）。 */
export function fmtSharesCompact(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—';
  const abs = Math.abs(value);
  const sign = value < 0 ? MINUS : '';
  const locale = getLocale();
  if (locale === 'en') {
    if (abs >= 1e9) return `${sign}${(abs / 1e9).toFixed(1)}B sh`;
    if (abs >= 1e6) return `${sign}${(abs / 1e6).toFixed(1)}M sh`;
    if (abs >= 1e3) return `${sign}${(abs / 1e3).toFixed(1)}K sh`;
    return `${sign}${EN_INT_FMT.format(Math.round(abs))} sh`;
  }
  const OKU = 1_0000_0000;
  const MAN = 1_0000;
  if (locale === 'zh') {
    if (abs >= OKU) return `${sign}${(abs / OKU).toFixed(1)}亿股`;
    if (abs >= MAN) return `${sign}${(abs / MAN).toFixed(1)}万股`;
    return `${sign}${ZH_INT_FMT.format(Math.round(abs))}股`;
  }
  if (abs >= OKU) return `${sign}${(abs / OKU).toFixed(1)}億株`;
  if (abs >= MAN) return `${sign}${(abs / MAN).toFixed(1)}万株`;
  return `${sign}${JA_INT_FMT.format(Math.round(abs))}株`;
}

/** 株数。桁を落とさずカンマ区切りで出す（karauri 等の開示元と突き合わせるため）。 */
export function fmtShares(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—';
  return JA_INT_FMT.format(Math.round(value));
}

/** 水準（比率そのもの）。**符号を付けない。**
 *
 * `fmtPct` は必ず符号を付けるので、変化には正しいが水準には誤り —— 空売り
 * 残高 5.23% が「+5.23%」と出ると増加したように読める。実際そうなっていた。 */
export function fmtPctLevel(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—';
  return `${(value * 100).toFixed(digits)}%`;
}

export function fmtPct(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—';
  const pct = value * 100;
  const sign = pct > 0 ? '+' : pct < 0 ? MINUS : '';
  return `${sign}${Math.abs(pct).toFixed(digits)}%`;
}

export function fmtSigned(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—';
  const sign = value > 0 ? '+' : value < 0 ? MINUS : '';
  return `${sign}${Math.abs(value).toFixed(digits)}`;
}

export function fmtScore(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—';
  return `${Math.round(value)}`;
}

/** 'YYYY-MM-DD' → 'M/D'（JST の暦日文字列をそのまま分解; TZ 変換しない）。 */
export function fmtDateShort(isoDate: string | null | undefined): string {
  if (!isoDate) return '—';
  const parts = isoDate.slice(0, 10).split('-');
  if (parts.length !== 3) return isoDate;
  return `${Number(parts[1])}/${Number(parts[2])}`;
}

const JST_DATE_SHORT_FMT = new Intl.DateTimeFormat('en-US', {
  timeZone: 'Asia/Tokyo',
  month: 'numeric',
  day: 'numeric',
});

/** ISO タイムスタンプ → JST 'M/D'。UTC 日付を切らない。 */
export function fmtJstDateShort(iso: string | null | undefined): string {
  if (!iso) return '—';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '—';
  return JST_DATE_SHORT_FMT.format(date);
}

export function fmtDate(isoDate: string | null | undefined): string {
  if (!isoDate) return '—';
  return isoDate.slice(0, 10);
}

let monthShortTag = '';
let monthShortFmt: Intl.DateTimeFormat | null = null;

function getMonthShortFmt(): Intl.DateTimeFormat {
  const tag = localeTag();
  if (!monthShortFmt || tag !== monthShortTag) {
    monthShortTag = tag;
    monthShortFmt = new Intl.DateTimeFormat(tag, { month: 'short' });
  }
  return monthShortFmt;
}

/** 电报行日期锚：日数字 + 本地化短月。ISO 日历日原样拆，不做 TZ 换算。 */
export function dateAnchorParts(iso: string | null | undefined): { day: number; monthShort: string } | null {
  if (!iso) return null;
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  if (!match) return null;
  const month = Number(match[2]);
  const day = Number(match[3]);
  if (!month || !day) return null;
  return {
    day,
    monthShort: getMonthShortFmt().format(new Date(Number(match[1]), month - 1, 1)),
  };
}

const JST_TIME_FMT = new Intl.DateTimeFormat('ja-JP', {
  timeZone: 'Asia/Tokyo',
  hour: '2-digit',
  minute: '2-digit',
  hourCycle: 'h23',
});

const JST_DATETIME_FMT = new Intl.DateTimeFormat('ja-JP', {
  timeZone: 'Asia/Tokyo',
  month: 'numeric',
  day: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
  hourCycle: 'h23',
});

/** ISO タイムスタンプ → JST 'M/D HH:mm'。 */
export function fmtJstDateTime(iso: string | null | undefined): string {
  if (!iso) return '—';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '—';
  return JST_DATETIME_FMT.format(date);
}

export function fmtJstTime(iso: string | null | undefined): string {
  if (!iso) return '—';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '—';
  return JST_TIME_FMT.format(date);
}

/** 相対時刻の通常形（刚刚 / 5 分钟前 / 3 小时前 / 2 天前）。 */
export function fmtRelative(iso: string | null | undefined, now: number = Date.now()): string {
  if (!iso) return '—';
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return '—';
  const min = Math.floor((now - then) / 60_000);
  if (min < 1) return t('刚刚');
  if (min < 60) return t('{n} 分钟前', { n: min });
  const hours = Math.floor(min / 60);
  if (hours < 24) return t('{n} 小时前', { n: hours });
  return t('{n} 天前', { n: Math.floor(hours / 24) });
}

/** 相対時刻の短縮形（5分 / 3時間 / 2日）— 言語非依存の狭い列用。 */
export function fmtRelativeShort(iso: string | null | undefined, now: number = Date.now()): string {
  if (!iso) return '—';
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return '—';
  const seconds = Math.max(0, (now - then) / 1000);
  if (seconds < 90) return '1m';
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)}h`;
  return `${Math.round(seconds / 86400)}d`;
}

/** 騰落方向: up / down / flat / null（欠損）。 */
export function direction(value: number | null | undefined): 'up' | 'down' | 'flat' | null {
  if (value === null || value === undefined || !Number.isFinite(value)) return null;
  if (value > 0.00005) return 'up';
  if (value < -0.00005) return 'down';
  return 'flat';
}

const JST_TIME_SEC_FMT = new Intl.DateTimeFormat('ja-JP', {
  timeZone: 'Asia/Tokyo',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hourCycle: 'h23',
});

/** epoch 秒 → JST の HH:MM（遅延気配の「いつの値か」表示用） */
export function fmtTimeJst(epochSeconds: number): string {
  return JST_TIME_FMT.format(new Date(epochSeconds * 1000));
}

/** 顶栏时钟：当前瞬间的 JST HH:mm。 */
export function fmtJstClock(date: Date | number): string {
  return JST_TIME_FMT.format(new Date(date));
}

export function fmtTimeHHMMSS(epochMs: number): string {
  return JST_TIME_SEC_FMT.format(new Date(epochMs));
}
