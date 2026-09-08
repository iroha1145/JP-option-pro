import type { EarningsUpcomingItem } from '@/api/types';
import { statusMeta } from './types';

export function earningsChipLabel(item: EarningsUpcomingItem): string {
  const meta = statusMeta(item.status);
  return [item.name_ja ?? item.display_code, item.quarter_label, meta.label].filter(Boolean).join(' · ');
}

export function EarningsChipContent({ item }: { item: EarningsUpcomingItem }) {
  const meta = statusMeta(item.status);
  return (
    <>
      <span className="block text-caption font-semibold text-ink-800">{item.name_ja ?? item.display_code}</span>
      <span className="mt-1 block font-mono text-micro text-ink-500">{item.display_code}</span>
      <span className="mt-1 block text-micro text-ink-500">
        {[item.quarter_label, meta.label].filter(Boolean).join(' · ')}
      </span>
    </>
  );
}
