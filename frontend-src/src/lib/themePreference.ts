/**
 * 外观主题：跟随系统 / 浅色 / 深色。
 * 深色色值对齐 Cloud Monitor（#191B20 页底、#24262D 卡片、#F1F3F5 主字、#8ABCF0 主色）。
 * 默认跟随设备 prefers-color-scheme；用户手动选择后写入本地存储。
 */
export type ThemePreference = 'system' | 'light' | 'dark';
export type ThemeAppearance = 'light' | 'dark';

export const THEME_STORAGE_KEY = 'optixjp_theme';

export const THEME_CHROME = {
  light: {
    paper: '#F6F7F9',
    paper2: '#FAFBFC',
    card: '#FFFFFF',
    ink900: '#0D1626',
    ink600: '#3D4A68',
    ink400: '#626F8B',
    ink300: '#B7BFD3',
    line: '#E9ECF1',
    lineChart: '#EDF0F4',
    brand600: '#2E46E0',
    brand500: '#3B59F2',
    brand400: '#6B82FF',
    warn600: '#E8930C',
    ai600: '#0B7285',
    tooltipFg: '#3D4A68',
  },
  dark: {
    paper: '#191B20',
    paper2: '#1D1F24',
    card: '#24262D',
    ink900: '#F1F3F5',
    ink600: '#B0B6C0',
    ink400: '#A0A8B5',
    ink300: '#5C6470',
    line: '#323640',
    lineChart: '#353944',
    brand600: '#8ABCF0',
    brand500: '#9BC8F8',
    brand400: '#B5D4F5',
    warn600: '#E8A83A',
    ai600: '#5BC0C8',
    tooltipFg: '#F1F3F5',
  },
} as const;

export const THEME_META_COLOR = {
  light: THEME_CHROME.light.paper,
  dark: THEME_CHROME.dark.paper,
} as const;

const listeners = new Set<() => void>();
let currentPreference: ThemePreference = readStoredPreference();
let storageBound = false;
let boundMedia: MediaQueryList | null = null;

function isPreference(value: unknown): value is ThemePreference {
  return value === 'system' || value === 'light' || value === 'dark';
}

function readStoredPreference(): ThemePreference {
  if (typeof window === 'undefined') return 'system';
  try {
    const stored = window.localStorage.getItem(THEME_STORAGE_KEY);
    return isPreference(stored) ? stored : 'system';
  } catch {
    return 'system';
  }
}

function persist(preference: ThemePreference): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, preference);
  } catch {
    /* ignore quota / private-mode failures */
  }
}

function emit(): void {
  listeners.forEach((listener) => listener());
}

export function readSystemAppearance(): ThemeAppearance {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return 'light';
  try {
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  } catch {
    return 'light';
  }
}

export function resolveTheme(
  preference: ThemePreference = getThemePreference(),
  system: ThemeAppearance = readSystemAppearance(),
): ThemeAppearance {
  return preference === 'system' ? system : preference;
}

function onStorage(event: StorageEvent): void {
  if (event.key !== THEME_STORAGE_KEY) return;
  const next: ThemePreference = isPreference(event.newValue) ? event.newValue : 'system';
  if (next === currentPreference) return;
  currentPreference = next;
  applyTheme(next);
  emit();
}

function onSystemChange(): void {
  if (currentPreference !== 'system') return;
  applyTheme('system');
  emit();
}

function ensureStorageListener(): void {
  if (storageBound || typeof window === 'undefined') return;
  storageBound = true;
  window.addEventListener('storage', onStorage);
}

function ensureMediaListener(): void {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return;
  let media: MediaQueryList;
  try {
    media = window.matchMedia('(prefers-color-scheme: dark)');
  } catch {
    return;
  }
  if (boundMedia === media) return;
  boundMedia?.removeEventListener('change', onSystemChange);
  boundMedia = media;
  media.addEventListener('change', onSystemChange);
}

export function getThemePreference(): ThemePreference {
  return currentPreference;
}

export function getResolvedTheme(): ThemeAppearance {
  return resolveTheme(currentPreference);
}

export function applyTheme(preference: ThemePreference = getThemePreference()): void {
  currentPreference = preference;
  ensureMediaListener();
  if (typeof document === 'undefined') return;
  const appearance = resolveTheme(preference);
  const root = document.documentElement;
  root.classList.toggle('dark', appearance === 'dark');
  root.setAttribute('data-theme', appearance);
  root.setAttribute('data-theme-preference', preference);
  root.style.colorScheme = appearance;
  const themeColor = document.querySelector('meta[name="theme-color"]');
  if (themeColor) themeColor.setAttribute('content', THEME_META_COLOR[appearance]);
  const colorScheme = document.querySelector('meta[name="color-scheme"]');
  if (colorScheme) colorScheme.setAttribute('content', 'light dark');
}

export function setThemePreference(preference: ThemePreference): void {
  currentPreference = preference;
  persist(preference);
  applyTheme(preference);
  emit();
}

export function subscribeTheme(listener: () => void): () => void {
  ensureStorageListener();
  ensureMediaListener();
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function themeChrome(appearance: ThemeAppearance = getResolvedTheme()) {
  return THEME_CHROME[appearance];
}
