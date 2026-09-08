/** Match the backend's four/five-character Japanese security identifiers.
 * Letters are significant. A non-zero fifth character is never discarded.
 */
export function canonicalCode(code: string | null | undefined): string | null {
  const text = String(code ?? '').trim().toUpperCase().replace(/\.(?:T|JP)$/, '');
  if (!/^[0-9][0-9A-Z]{3,4}$/.test(text)) return null;
  return text.length === 4 ? `${text}0` : text;
}

export function codesMatch(left?: string | null, right?: string | null): boolean {
  const a = canonicalCode(left);
  return a !== null && a === canonicalCode(right);
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
