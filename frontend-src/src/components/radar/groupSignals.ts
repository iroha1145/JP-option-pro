/**
 * 同一只股票的多条雷达信号合并成一组（纯函数，不读界面状态、不做格式化）。
 *
 * - 按 canonical_code 分组；组的先后按该股票在输入里第一次出现的位置。
 * - 每组的 primary 是告警优先级最高的一条；优先级缺失视为最低；同分保留输入先后。
 * - others 是同组其余信号，保持输入先后。不丢任何一条：所有组的 primary 与 others 合起来
 *   恰好是输入的全部事件。
 */
export interface GroupableSignal {
  event_id: string;
  canonical_code: string;
  alert_priority: number | null;
}

export interface SignalGroup<E extends GroupableSignal> {
  /** 分组键，即 canonical_code。 */
  key: string;
  primary: E;
  others: E[];
}

const rank = (value: number | null | undefined): number =>
  typeof value === 'number' && Number.isFinite(value) ? value : Number.NEGATIVE_INFINITY;

export function groupSignalsByStock<E extends GroupableSignal>(events: readonly E[]): SignalGroup<E>[] {
  const buckets = new Map<string, E[]>();
  for (const event of events) {
    const list = buckets.get(event.canonical_code);
    if (list) list.push(event);
    else buckets.set(event.canonical_code, [event]);
  }
  const groups: SignalGroup<E>[] = [];
  for (const [key, list] of buckets) {
    let best = 0;
    for (let index = 1; index < list.length; index += 1) {
      if (rank(list[index].alert_priority) > rank(list[best].alert_priority)) best = index;
    }
    groups.push({ key, primary: list[best], others: list.filter((_, index) => index !== best) });
  }
  return groups;
}
