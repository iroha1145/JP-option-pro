/** 雷达生命周期状态的色调：徽章底色、圆点与步进条共用一套映射。 */
export type RadarTone = 'brand' | 'up' | 'down' | 'ink' | 'warn';

export const RADAR_STATE_TONE: Record<string, RadarTone> = {
  discovered: 'brand',
  watching: 'brand',
  triggered: 'warn',
  confirmed: 'up',
  holding: 'up',
  retesting: 'warn',
  retest_held: 'up',
  reaccelerating: 'up',
  extended: 'warn',
  failed: 'down',
  expired: 'ink',
};

export const RADAR_TONE_CHIP: Record<RadarTone, string> = {
  brand: 'radar-chip-brand',
  up: 'radar-chip-up',
  down: 'radar-chip-down',
  ink: 'radar-chip-neutral',
  warn: 'radar-chip-warn',
};

export const radarStateChipClass = (state: string): string =>
  RADAR_TONE_CHIP[RADAR_STATE_TONE[state] ?? 'ink'];
