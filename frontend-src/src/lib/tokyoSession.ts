/** JST 立会区分。与 backend/app/providers/intraday/contract.py 同口径；不判节假日。 */

export type TokyoSession = 'pre' | 'morning' | 'lunch' | 'afternoon' | 'closed';

export function tokyoSession(now: Date | number = Date.now()): TokyoSession {
  const parts = new Intl.DateTimeFormat('en-GB', {
    timeZone: 'Asia/Tokyo',
    weekday: 'short',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).formatToParts(new Date(now));
  const weekday = parts.find((part) => part.type === 'weekday')?.value ?? '';
  if (weekday === 'Sat' || weekday === 'Sun') return 'closed';
  const hour = Number(parts.find((part) => part.type === 'hour')?.value ?? '0');
  const minute = Number(parts.find((part) => part.type === 'minute')?.value ?? '0');
  const minutes = hour * 60 + minute;
  if (minutes < 9 * 60) return 'pre';
  if (minutes < 11 * 60 + 30) return 'morning';
  if (minutes < 12 * 60 + 30) return 'lunch';
  if (minutes <= 15 * 60 + 30) return 'afternoon';
  return 'closed';
}

export function tokyoSessionLabel(session: TokyoSession): string {
  switch (session) {
    case 'pre':
      return '开盘前';
    case 'morning':
      return '上午交易';
    case 'lunch':
      return '午间休市';
    case 'afternoon':
      return '下午交易';
    default:
      return '休市';
  }
}
