import { useSyncExternalStore } from 'react';
import {
  getResolvedTheme,
  getThemePreference,
  subscribeTheme,
  type ThemeAppearance,
  type ThemePreference,
} from '@/lib/themePreference.ts';

export function useThemePreference(): ThemePreference {
  return useSyncExternalStore(subscribeTheme, getThemePreference, getThemePreference);
}

/** 顶栏、登录页与图表共用同一外部快照，避免各处独立 useState。 */
export function useTheme(): ThemeAppearance {
  return useSyncExternalStore(subscribeTheme, getResolvedTheme, getResolvedTheme);
}
