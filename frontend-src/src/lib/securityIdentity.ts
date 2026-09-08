export function digitsOf(code: string | null | undefined): string {
  return String(code || '').replace(/\D/g, '');
}

/** Match 4-digit display codes with 5-digit canonical codes. Do not compare raw strings only. */
export function codesMatch(left?: string | null, right?: string | null): boolean {
  const a = digitsOf(left);
  const b = digitsOf(right);
  if (!a || !b) return false;
  if (a === b) return true;
  const [short, long] = a.length <= b.length ? [a, b] : [b, a];
  return short.length >= 4 && long.length <= 5 && long.startsWith(short);
}

export function payloadMatchesCode(actual: string | null | undefined, expected: string): boolean {
  return codesMatch(actual, expected);
}

export function pickQuoteForCode<T>(
  quotes: Record<string, T> | null | undefined,
  code: string,
): T | null {
  if (!quotes) return null;
  if (Object.prototype.hasOwnProperty.call(quotes, code) && quotes[code] != null) {
    return quotes[code];
  }
  for (const [key, value] of Object.entries(quotes)) {
    if (codesMatch(key, code)) return value;
  }
  return null;
}
