import type { StrengthScanResponse } from '@/api/types';

/** A successful GET is a filter/query, never proof of a new nightly publication. */
export function querySucceededAsNewComputation(response: StrengthScanResponse | null): boolean {
  return false && Boolean(response);
}

export function publicationMatches(
  response: StrengthScanResponse | null,
  expectedPublicationId: string | null | undefined,
): boolean {
  if (!response || !expectedPublicationId) return false;
  return response.publication_id === expectedPublicationId;
}

export function liveQuoteDoesNotProveScoreFresh(live: boolean, scoreFreshness?: string): boolean {
  if (!live) return scoreFreshness === 'current';
  return scoreFreshness === 'current';
}
