/** Recorded inside dataZoom window. Survives setOption / color / layer rebuilds. */

export interface ZoomWindow {
  start: number;
  end: number;
  pinnedEnd: boolean;
}

const DEFAULT_ZOOM_BARS = 126;

export function insideZoom(
  barCount: number,
  axes: number[],
  saved?: ZoomWindow | null,
  defaultBars = DEFAULT_ZOOM_BARS,
) {
  if (!Number.isSafeInteger(barCount) || barCount < 2) return undefined;
  const last = barCount - 1;
  const window = Number.isFinite(defaultBars) ? Math.max(2, Math.floor(defaultBars)) : DEFAULT_ZOOM_BARS;
  let startValue = Math.max(0, barCount - window);
  let endValue = last;
  if (saved && Number.isFinite(saved.start) && Number.isFinite(saved.end) && saved.end > saved.start) {
    const span = Math.min(last, Math.max(1, Math.round(saved.end - saved.start)));
    endValue = saved.pinnedEnd ? last : Math.min(last, Math.max(span, Math.round(saved.end)));
    startValue = endValue - span;
  }
  return [
    {
      type: 'inside' as const,
      xAxisIndex: axes,
      startValue,
      endValue,
      minValueSpan: 1,
      preventDefaultMouseMove: false,
      zoomOnMouseWheel: true,
      moveOnMouseMove: true,
      moveOnMouseWheel: false,
    },
    {
      type: 'slider' as const,
      xAxisIndex: axes,
      startValue,
      endValue,
      minValueSpan: 1,
      height: 16,
      bottom: 0,
      borderColor: 'transparent',
      fillerColor: 'rgba(46,70,224,0.12)',
      handleSize: 12,
      showDetail: false,
    },
  ];
}

export function zoomFromOption(
  option: {
    dataZoom?: Array<{ startValue?: unknown; endValue?: unknown; start?: unknown; end?: unknown }>;
  } | null | undefined,
  barCount: number,
): ZoomWindow | null {
  if (!Number.isSafeInteger(barCount) || barCount < 2) return null;
  const row = option?.dataZoom?.[0];
  const value = (index: unknown, percent: unknown) => typeof index === 'number' && Number.isFinite(index)
    ? index : typeof percent === 'number' && Number.isFinite(percent) ? percent * (barCount - 1) / 100 : NaN;
  const start = Math.max(0, Math.min(barCount - 1, Math.round(value(row?.startValue, row?.start))));
  const end = Math.max(0, Math.min(barCount - 1, Math.round(value(row?.endValue, row?.end))));
  if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) return null;
  return {
    start,
    end,
    pinnedEnd: end >= barCount - 1,
  };
}
