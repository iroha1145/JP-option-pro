/** Persist optional A0/T1 choices without overriding explicit originals. */

export const SCREENER_FOLLOW_DEFAULT = 'follow_default';
export const SCREENER_PRODUCTION = 'production';
export const SCREENER_A0 = 'a0_mid_long';
export const RADAR_FOLLOW_DEFAULT = 'follow_default';
export const RADAR_PRODUCTION = 'production';
export const RADAR_T1 = 't1_daily_priority';

export type ScreenerRankingChoice = 'follow_default' | 'production' | 'a0_mid_long';
export type RadarSortChoice = 'follow_default' | 'production' | 't1_daily_priority';

export interface AlgorithmPreferences {
  screenerRankingAlgorithm: ScreenerRankingChoice;
  radarSortAlgorithm: RadarSortChoice;
}

export const DEFAULT_ALGORITHM_PREFERENCES: AlgorithmPreferences = {
  screenerRankingAlgorithm: SCREENER_FOLLOW_DEFAULT,
  radarSortAlgorithm: RADAR_FOLLOW_DEFAULT,
};

export const LEGACY_PREFERENCE_STORAGE_KEY = 'optixjp.algorithmPreferences';

export function preferenceStorageKey(principal?: string | null): string {
  return principal ? `optixjp.algorithmPreferences:${principal}` : LEGACY_PREFERENCE_STORAGE_KEY;
}

function asScreenerChoice(value: unknown): ScreenerRankingChoice {
  if (value === SCREENER_PRODUCTION || value === SCREENER_A0 || value === SCREENER_FOLLOW_DEFAULT) {
    return value;
  }
  return SCREENER_FOLLOW_DEFAULT;
}

function asRadarChoice(value: unknown): RadarSortChoice {
  if (value === RADAR_PRODUCTION || value === RADAR_T1 || value === RADAR_FOLLOW_DEFAULT) {
    return value;
  }
  return RADAR_FOLLOW_DEFAULT;
}

function readStorage(key: string): Record<string, unknown> | null {
  if (typeof window === 'undefined') return null;
  try {
    const raw = window.localStorage.getItem(key);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Record<string, unknown>;
    return parsed && typeof parsed === 'object' ? parsed : null;
  } catch {
    return null;
  }
}

function writeStorage(key: string, value: AlgorithmPreferences | Record<string, unknown>): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // Quota / private mode must not crash the page.
  }
}

export function readAlgorithmPreferences(principal?: string | null): AlgorithmPreferences {
  const scoped = readStorage(preferenceStorageKey(principal));
  const legacy = principal ? null : readStorage(LEGACY_PREFERENCE_STORAGE_KEY);
  const parsed = scoped ?? legacy;
  if (!parsed) return { ...DEFAULT_ALGORITHM_PREFERENCES };
  return {
    screenerRankingAlgorithm: asScreenerChoice(
      parsed.screenerRankingAlgorithm ?? parsed.screener_ranking_algorithm,
    ),
    radarSortAlgorithm: asRadarChoice(parsed.radarSortAlgorithm ?? parsed.radar_sort_algorithm),
  };
}

export function writeAlgorithmPreferences(
  next: Partial<AlgorithmPreferences>,
  principal?: string | null,
): AlgorithmPreferences {
  const merged = { ...readAlgorithmPreferences(principal), ...next };
  const current = readStorage(preferenceStorageKey(principal)) ?? {};
  writeStorage(preferenceStorageKey(principal), {
    ...current,
    ...merged,
  } as AlgorithmPreferences & Record<string, unknown>);
  return merged;
}

export function markAlgorithmPreferencePendingSync(
  principal: string | null | undefined,
  pending: boolean,
): void {
  const key = preferenceStorageKey(principal);
  const current = readStorage(key) ?? readAlgorithmPreferences(principal);
  writeStorage(key, { ...current, pendingSync: pending } as AlgorithmPreferences & { pendingSync?: boolean });
}

export function algorithmPreferencePendingSync(principal?: string | null): boolean {
  const parsed = readStorage(preferenceStorageKey(principal));
  return parsed?.pendingSync === true;
}

export function algorithmPreferenceRevision(principal?: string | null): number {
  const parsed = readStorage(preferenceStorageKey(principal));
  const value = Number(parsed?.choiceRevision ?? 0);
  return Number.isFinite(value) ? value : 0;
}

export function bumpAlgorithmPreferenceRevision(principal?: string | null): number {
  const key = preferenceStorageKey(principal);
  const current = readStorage(key) ?? readAlgorithmPreferences(principal);
  const next = algorithmPreferenceRevision(principal) + 1;
  writeStorage(key, { ...current, choiceRevision: next } as AlgorithmPreferences & {
    choiceRevision?: number;
    pendingSync?: boolean;
  });
  return next;
}

export function shouldApplyRemotePreference(
  principal: string | null | undefined,
  startedRevision: number,
): boolean {
  if (algorithmPreferencePendingSync(principal)) return false;
  return algorithmPreferenceRevision(principal) === startedRevision;
}

export interface PreferenceIdentityGuard {
  startedEpoch: number;
  currentEpoch: number;
  currentPrincipal?: string | null;
}

let preferenceIdentityEpoch = 0;

export function currentPreferenceIdentityEpoch(): number {
  return preferenceIdentityEpoch;
}

export function bumpPreferenceIdentityEpoch(): number {
  preferenceIdentityEpoch += 1;
  return preferenceIdentityEpoch;
}

export function resetPreferenceIdentityEpoch(): void {
  preferenceIdentityEpoch = 0;
}

export function shouldApplyFetchedPreferences(
  principal: string | null | undefined,
  startedRevision: number,
  remotePrincipal: string | null | undefined,
  identity?: PreferenceIdentityGuard,
): boolean {
  if (identity) {
    if (identity.startedEpoch !== identity.currentEpoch) return false;
    if (identity.currentEpoch !== preferenceIdentityEpoch) return false;
    if (
      identity.currentPrincipal !== undefined &&
      (identity.currentPrincipal ?? '') !== (principal ?? '')
    ) {
      return false;
    }
  }
  if (remotePrincipal == null || remotePrincipal === '') return false;
  return shouldApplyRemotePreference(principal, startedRevision);
}

export function canCommitPreferenceWriteResult(
  startedEpoch: number,
  currentPrincipal: string | null | undefined,
  capturedPrincipal: string | null | undefined,
): boolean {
  if (startedEpoch !== preferenceIdentityEpoch) return false;
  return (currentPrincipal ?? '') === (capturedPrincipal ?? '');
}

export function preferencePrincipalFromAccess(
  isOwner: boolean,
  accountUsername: string | null | undefined,
): string {
  return isOwner ? 'owner' : accountUsername ? `account:${accountUsername}` : 'visitor';
}

export function a0ViewSupported(timeframe: string, profile: string): boolean {
  return timeframe === 'all' && profile === 'balanced';
}
