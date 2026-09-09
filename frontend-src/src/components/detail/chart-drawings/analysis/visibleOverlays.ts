import { filterOverlays, type AnalysisOverlay } from './mapBundle.ts';
import { prepareStructuralOverlays, type StructuralBar } from './structuralOverlays.ts';
import { selectSmartOverlays } from './smartLines.ts';
import type { LayerSettings } from './settings.ts';

/** One visibility gate for server and local annotations. Moving averages have
 * their own layer switches; turning drawings off must not switch data sources. */
export function visibleAnalysisOverlays(
  candidates: readonly AnalysisOverlay[],
  bars: readonly StructuralBar[],
  settings: LayerSettings,
  drawingsEnabled: boolean,
): AnalysisOverlay[] {
  if (!drawingsEnabled) return filterOverlays(candidates.filter(row => row.kind === 'ma'), settings);
  const filtered = filterOverlays(prepareStructuralOverlays(candidates, bars), { ...settings, maxPatterns: 64 });
  return selectSmartOverlays(filtered, bars, settings.maxPatterns);
}
