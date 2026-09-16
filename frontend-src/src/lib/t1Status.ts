export type T1Status = 'met' | 'unmet' | 'pending_close' | 'unavailable' | 'not_applicable';

export function t1StatusOf(event: { t1_priority?: { status?: string | null } | null } | null | undefined): T1Status | null {
  const raw = event?.t1_priority?.status;
  if (raw === 'pending') return 'pending_close';
  if (raw === 'met' || raw === 'unmet' || raw === 'pending_close' || raw === 'unavailable' || raw === 'not_applicable') {
    return raw;
  }
  return null;
}

export function t1StatusLabelKey(status: T1Status): string {
  switch (status) {
    case 'met':
      return 'T1 已确认';
    case 'unmet':
      return 'T1 未满足';
    case 'pending_close':
      return 'T1 待收盘';
    case 'unavailable':
      return 'T1 暂不可用';
    case 'not_applicable':
      return 'T1 不适用';
    default:
      return 'T1';
  }
}
