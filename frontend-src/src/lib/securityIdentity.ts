/** Keep the same identity rules as backend/app/domain/symbols.py. */
function canonicalCode(code: string | null | undefined): string | null {
  const text = String(code ?? '').trim().toUpperCase().split('.', 1)[0];
  if (!/^[0-9][0-9A-Z]{3,4}$/.test(text)) return null;
  return text.length === 4 ? `${text}0` : text;
}

/** Four-character display codes append 0; letters and other fifth characters remain significant. */
export function codesMatch(left?: string | null, right?: string | null): boolean {
  const a = canonicalCode(left);
  const b = canonicalCode(right);
  return a !== null && a === b;
}

export function payloadMatchesCode(actual: string | null | undefined, expected: string): boolean {
  return codesMatch(actual, expected);
}

export function pickQuoteForCode<T>(
  quotes: Record<string, T> | null | undefined,
  code: string,
): T | null {
  const expected = canonicalCode(code);
  if (!quotes || expected === null) return null;
  if (Object.prototype.hasOwnProperty.call(quotes, code) && quotes[code] != null) {
    return quotes[code];
  }
  for (const [key, value] of Object.entries(quotes)) {
    if (value != null && canonicalCode(key) === expected) return value;
  }
  return null;
}
