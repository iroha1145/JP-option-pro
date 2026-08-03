/**
 * 数値・日付フォーマット（日本市場版）。
 *
 * - タイムゾーンは常に Asia/Tokyo。閲覧者のローカル時刻でデータ日付を
 *   ずらさない（旧プロジェクトの ET バグの教訓）。
 * - 円金額は整数表示が基本、大きい値は 万 / 億 / 兆 に圧縮。
 * - 欠損は常に '—'。0 と欠損を混同しない。
 * - マイナスは U+2212 を使う（ハイフンより判読しやすい）。
 */

const MINUS = '−';

export function fmtPrice(value: number | null | undefined, digits?: number): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—';
  const resolved = digits ?? (Math.abs(value) < 100 ? 1 : 0);
  return value.toLocaleString('ja-JP', {
    minimumFractionDigits: resolved,
    maximumFractionDigits: resolved,
  });
}

export function fmtYen(value: number | null | undefined): string {
  const text = fmtPrice(value, 0);
  return text === '—' ? text : `¥${text}`;
}

/** 円金額の 万/億/兆 圧縮（例: 123.4億）。 */
export function fmtYenCompact(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—';
  const abs = Math.abs(value);
  const sign = value < 0 ? MINUS : '';
  const CHO = 1_0000_0000_0000; // 兆
  const OKU = 1_0000_0000; // 億
  const MAN = 1_0000; // 万
  if (abs >= CHO) return `${sign}${(abs / CHO).toFixed(digits)}兆`;
  if (abs >= OKU) return `${sign}${(abs / OKU).toFixed(digits)}億`;
  if (abs >= MAN) return `${sign}${(abs / MAN).toFixed(0)}万`;
  return `${sign}${abs.toLocaleString('ja-JP', { maximumFractionDigits: 0 })}`;
}

/** 株数。桁を落とさずカンマ区切りで出す（karauri 等の開示元と突き合わせるため）。 */
export function fmtShares(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—';
  return Math.round(value).toLocaleString('ja-JP');
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

export function fmtDate(isoDate: string | null | undefined): string {
  if (!isoDate) return '—';
  return isoDate.slice(0, 10);
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

/** epoch 秒 → JST の HH:MM（遅延気配の「いつの値か」表示用） */
export function fmtTimeJst(epochSeconds: number): string {
  return new Intl.DateTimeFormat('ja-JP', {
    timeZone: 'Asia/Tokyo', hour: '2-digit', minute: '2-digit', hour12: false,
  }).format(new Date(epochSeconds * 1000));
}
