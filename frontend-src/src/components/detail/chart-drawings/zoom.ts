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
) {
  if (barCount <= DEFAULT_ZOOM_BARS) return undefined;
  const last = barCount - 1;
  let startValue = barCount - DEFAULT_ZOOM_BARS;
  let endValue = last;
  if (saved) {
    const span = Math.max(1, saved.end - saved.start);
    endValue = saved.pinnedEnd ? last : Math.min(last, Math.max(1, saved.end));
    startValue = Math.max(0, Math.min(endValue - 1, saved.pinnedEnd ? endValue - span : saved.start));
  }
  return [
    {
      type: 'inside' as const,
      xAxisIndex: axes,
      startValue,
      endValue,
      minValueSpan: 15,
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
  const row = option?.dataZoom?.[0];
  const start = Number(row?.startValue ?? row?.start);
  const end = Number(row?.endValue ?? row?.end);
  if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) return null;
  return {
    start: Math.max(0, Math.round(start)),
    end: Math.round(end),
    pinnedEnd: Math.round(end) >= barCount - 1,
  };
}
