import { useCallback, useEffect, useRef, useState } from 'react';
import type { ChartOption, EChartsInstance } from '@/lib/chart';
import { insideZoom, zoomFromOption, type ZoomWindow } from './zoom.ts';

/** Preserve the user's date window through polling, layer and color rebuilds.
 * Each security/interval owns its window; only a window at the end follows new bars. */
export function useChartZoom(scope: string, barCount: number, defaultBars = 126) {
  const [chart, onInit] = useState<EChartsInstance | null>(null);
  const saved = useRef<{ scope: string; window: ZoomWindow } | null>(null);
  useEffect(() => { saved.current = null; }, [scope]);
  useEffect(() => {
    if (!chart || chart.isDisposed()) return;
    const handler = () => {
      if (chart.isDisposed()) return;
      const window = zoomFromOption(chart.getOption() as Parameters<typeof zoomFromOption>[0], barCount);
      if (window) saved.current = { scope, window };
    };
    chart.on('datazoom', handler);
    return () => { if (!chart.isDisposed()) chart.off('datazoom', handler); };
  }, [chart, barCount, scope]);

  const prepareOption = useCallback((option: ChartOption): ChartOption => {
    const current = saved.current;
    if (!current || current.scope !== scope || !Array.isArray(option.dataZoom)) return option;
    const restored = insideZoom(barCount, [], current.window, defaultBars)?.[0];
    if (!restored) return option;
    return { ...option, dataZoom: option.dataZoom.map(row => ({
      ...row, startValue: restored.startValue, endValue: restored.endValue,
    })) };
  }, [barCount, defaultBars, scope]);

  return { chart, onInit, prepareOption };
}
