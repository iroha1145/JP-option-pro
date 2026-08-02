/** 领域 API 模块：registry 走共享注册表，其余直连。 */

import { del, get, patch as patchVerb, post, toQuery } from './client.ts';
import { registryGet } from './queryRegistry.ts';
import type {
  AccessStatus,
  DataStatusResponse,
  EarningsCalendarItem,
  EarningsRecentItem,
  MarketOverview,
  RadarCurrent,
  RadarEvent,
  ScreenerResponse,
  SearchResult,
  SettingsView,
  StockBar,
  StockOverview,
  WatchlistItem,
} from './types.ts';

export const marketApi = {
  overview(): Promise<MarketOverview> {
    return registryGet<MarketOverview>('/market/overview');
  },
  indexSeries(code: string, limit = 250) {
    return get<{ index_code: string; name: string; data_through: string | null; bars: { trade_date: string; close: number | null }[] }>(
      `/market/indices/${encodeURIComponent(code)}?${toQuery({ limit })}`,
    );
  },
};

export const stocksApi = {
  search(q: string): Promise<{ query: string; results: SearchResult[] }> {
    return get(`/stocks/search?${toQuery({ q })}`);
  },
  overview(code: string): Promise<StockOverview> {
    return get(`/stocks/${encodeURIComponent(code)}`);
  },
  chart(code: string, range: string): Promise<{ canonical_code: string; display_code: string; range: string; data_through: string | null; bars: StockBar[] }> {
    return get(`/stocks/${encodeURIComponent(code)}/chart?${toQuery({ range })}`);
  },
};

export interface ScreenerQueryBody {
  markets?: string[];
  sectors?: string[];
  watchlist_codes?: string[];
  min_price?: number;
  max_price?: number;
  min_avg_turnover?: number;
  min_turnover_ratio?: number;
  max_pct_from_high_252?: number;
  ma_alignment?: boolean;
  above_ma25?: boolean;
  above_ma75?: boolean;
  above_ma200?: boolean;
  min_return_20d?: number;
  min_rs_topix_63d?: number;
  min_volatility_contraction?: number;
  min_listed_days?: number;
  max_margin_ratio?: number;
  sort_by?: string;
  sort_dir?: 'asc' | 'desc';
  limit?: number;
  offset?: number;
}

export const screenerApi = {
  options() {
    return get<{ markets: { code: string; name: string }[]; sectors: { code: string; name: string }[]; sort_keys: string[] }>(
      '/screener/options',
    );
  },
  query(body: ScreenerQueryBody): Promise<ScreenerResponse> {
    return post('/screener/query', body);
  },
};

export const watchlistApi = {
  list(): Promise<{ items: WatchlistItem[] }> {
    return get('/watchlist');
  },
  add(code: string) {
    return post<{ canonical_code: string; created: boolean }>(`/watchlist/${encodeURIComponent(code)}`);
  },
  update(code: string, body: { note?: string | null; marked_important?: boolean }) {
    return patchVerb<{ canonical_code: string; updated: boolean }>(
      `/watchlist/${encodeURIComponent(code)}`,
      body,
    );
  },
  remove(code: string) {
    return del<{ canonical_code: string; removed: boolean }>(`/watchlist/${encodeURIComponent(code)}`);
  },
};

export const earningsApi = {
  calendar(start?: string, end?: string): Promise<{ coverage_note: string; items: EarningsCalendarItem[] }> {
    const query = toQuery({ start, end });
    return query
      ? get(`/earnings/calendar?${query}`)
      : registryGet('/earnings/calendar');
  },
  recent(days = 7): Promise<{ items: EarningsRecentItem[] }> {
    return days === 7 ? registryGet('/earnings/recent') : get(`/earnings/recent?${toQuery({ days })}`);
  },
};

export const radarApi = {
  current(params?: { states?: string; signals?: string; min_priority?: number; limit?: number }): Promise<RadarCurrent> {
    const query = params ? toQuery(params) : '';
    return query ? get(`/radar/current?${query}`) : registryGet('/radar/current');
  },
  event(eventId: string): Promise<RadarEvent> {
    return get(`/radar/events/${encodeURIComponent(eventId)}`);
  },
  forSecurity(code: string): Promise<{ canonical_code: string; display_code: string; events: RadarEvent[] }> {
    return get(`/radar/securities/${encodeURIComponent(code)}`);
  },
};

export const dataStatusApi = {
  get(): Promise<DataStatusResponse> {
    return registryGet('/data-status');
  },
};

export const settingsApi = {
  get(): Promise<SettingsView> {
    return registryGet('/settings');
  },
};

export const accessApi = {
  status(): Promise<AccessStatus> {
    return get('/access/status');
  },
  login(password: string) {
    return post<{ logged_in: boolean }>('/access/login', { password });
  },
  logout() {
    return post<{ logged_in: boolean }>('/access/logout');
  },
};

export const workerApi = {
  status() {
    return registryGet<Record<string, unknown>>('/worker/status');
  },
  trigger(actionType: string) {
    return post<{ action_type: string; action_id: number | null; status: string; duplicate: boolean }>(
      `/worker/actions/${encodeURIComponent(actionType)}`,
    );
  },
};

export const newsApi = {
  feed(hours = 72) {
    return get<{ mode: string; items: unknown[]; note_ja?: string }>(`/news/feed?${toQuery({ hours })}`);
  },
};
