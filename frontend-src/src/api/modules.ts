/** 领域 API 模块：registry 走共享注册表，其余直连。 */

import { del, get, patch as patchVerb, post, toQuery, type RequestOptions } from './client.ts';
import { registryGet } from './queryRegistry.ts';
import type {
  AccessStatus,
  DataStatusResponse,
  EarningsRecentItem,
  EarningsUpcomingResponse,
  IntradayChart,
  TickView,
  MarketOverview,
  IntradayQuotesResponse,
  IntradaySectorsResponse,
  IntradayOverlayResponse,
  SectorMemberSort,
  SectorMembersView,
  NewsFeedResponse,
  NewsHotspotGroup,
  NewsSecurityRow,
  NewsStatus,
  RadarCurrent,
  RadarEvent,
  ShortMonitorDetail,
  ShortMonitorEvents,
  ShortMonitorOverview,
  ShortMonitorRankings,
  ShortMonitorView,
  SearchResult,
  StockBar,
  StockOverview,
  StrengthProfilesMeta,
  StrengthScanResponse,
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
  intradaySectors(): Promise<IntradaySectorsResponse> {
    return get('/quotes/sectors/intraday', { timeoutMs: 60_000, priority: 'low' });
  },
  sectorMembers(code: string, sort: SectorMemberSort, limit = 12): Promise<SectorMembersView> {
    return get(`/market/sectors/${encodeURIComponent(code)}/members?${toQuery({ sort, limit })}`);
  },
};

export const stocksApi = {
  search(q: string, options?: RequestOptions): Promise<{ query: string; results: SearchResult[] }> {
    return get(`/stocks/search?${toQuery({ q })}`, options);
  },
  overview(code: string): Promise<StockOverview> {
    return get(`/stocks/${encodeURIComponent(code)}`);
  },
  chart(code: string, range: string): Promise<{ canonical_code: string; display_code: string; range: string; data_through: string | null; chart_analysis?: Record<string, unknown> | null; bars: StockBar[] }> {
    return get(`/stocks/${encodeURIComponent(code)}/chart?${toQuery({ range })}`);
  },
  intradayChart(code: string, interval: '1m' | '5m' | '60m'): Promise<IntradayChart> {
    return get(`/stocks/${encodeURIComponent(code)}/chart?${toQuery({ interval })}`);
  },
  intradayQuotes(codes: string[]): Promise<IntradayQuotesResponse> {
    return get(`/quotes/intraday?${toQuery({ codes: codes.join(',') })}`, { priority: 'low' });
  },
  tickView(code: string): Promise<TickView> {
    return get(`/stocks/${encodeURIComponent(code)}/ticks`);
  },
};

export const watchlistApi = {
  list(): Promise<{ items: WatchlistItem[]; principal?: 'owner' | 'account'; max_items?: number | null }> {
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
  upcoming(): Promise<EarningsUpcomingResponse> {
    return get('/earnings/upcoming');
  },
  recent(days = 7): Promise<{ items: EarningsRecentItem[] }> {
    return days === 7 ? registryGet('/earnings/recent') : get(`/earnings/recent?${toQuery({ days })}`);
  },
};

export const quotesApi = {
  overlay(scope: 'radar' | 'screener', limit = 200): Promise<IntradayOverlayResponse> {
    return get(`/quotes/overlay?${toQuery({ scope, limit })}`, { priority: 'low' });
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
};

export const shortMonitorApi = {
  overview(date?: string): Promise<ShortMonitorOverview> {
    return get(date ? `/short-monitor/overview?${toQuery({ date })}` : '/short-monitor/overview');
  },
  rankings(params: {
    view?: ShortMonitorView;
    date?: string;
    states?: string;
    flags?: string;
    markets?: string;
    sectors?: string;
    codes?: string;
    institutions?: string;
    min_confidence?: number;
    min_turnover?: number;
    /** 0..3：0 不限，2 中及以上，3 仅高。 */
    min_crowding?: number;
    /** 默认 false：排行不含 ETF 与 ETN。 */
    include_funds?: boolean;
    order_by?: string;
    order_dir?: 'asc' | 'desc';
    limit?: number;
    offset?: number;
  } = {}): Promise<ShortMonitorRankings> {
    const query = toQuery(params);
    return get(query ? `/short-monitor/rankings?${query}` : '/short-monitor/rankings');
  },
  stock(code: string, date?: string): Promise<ShortMonitorDetail> {
    const suffix = date ? `?${toQuery({ date })}` : '';
    return get(`/short-monitor/stocks/${encodeURIComponent(code)}${suffix}`);
  },
  events(code: string, params: { limit?: number; offset?: number } = {}): Promise<ShortMonitorEvents> {
    const query = toQuery(params);
    return get(`/short-monitor/stocks/${encodeURIComponent(code)}/events${query ? `?${query}` : ''}`);
  },
};

export const dataStatusApi = {
  get(): Promise<DataStatusResponse> {
    return registryGet('/data-status');
  },
};

export const accessApi = {
  status(): Promise<AccessStatus> {
    return get('/access/status');
  },
  /** username 省略 = owner（admin）；其余用户名走访客账号（与美股版共库）。 */
  login(password: string, username = 'admin') {
    return post<{ logged_in: boolean; account?: { logged_in: boolean; username: string } }>(
      '/access/login',
      { username, password },
    );
  },
  logout() {
    return post<{ logged_in: boolean }>('/access/logout');
  },
};

export const accountApi = {
  register(username: string, password: string) {
    return post<{ logged_in: boolean; username: string }>('/account/register', { username, password });
  },
};

export const workerApi = {
  trigger(actionType: string, body?: { code?: string }) {
    return post<{
      action_type: string;
      action_id: number | null;
      status: string;
      duplicate: boolean;
      accepted?: boolean;
      reason?: string;
    }>(
      `/worker/actions/${encodeURIComponent(actionType)}`,
      body,
    );
  },
  action(actionId: number) {
    return get<{
      action_id: number;
      action_type: string;
      status: string;
      error_code?: string | null;
      result?: Record<string, unknown>;
    }>(`/worker/actions/${actionId}`, { cache: 'reload' });
  },
};

export interface StrengthScanParams {
  timeframe?: string;
  profile?: string;
  top?: number;
  sector_id?: string;
  min_price?: number;
  max_price?: number;
  min_avg_turnover?: number;
  tier?: string;
  min_score?: number;
}

export const strengthApi = {
  scan(params: StrengthScanParams = {}, options?: RequestOptions): Promise<StrengthScanResponse> {
    return get(`/strength/scan?${toQuery({ ...params })}`, options);
  },
  profiles(): Promise<StrengthProfilesMeta> {
    return registryGet('/strength/profiles');
  },
};

export const newsApi = {
  feed(params: { hours?: number; category?: string; only_securities?: boolean; min_importance?: number } = {}) {
    return get<NewsFeedResponse>(`/news/feed?${toQuery({ ...params })}`);
  },
  hotspots(hours = 72) {
    return get<{ window_hours?: number; groups: NewsHotspotGroup[]; note_ja?: string }>(
      `/news/hotspots?${toQuery({ hours })}`,
    );
  },
  securities(hours = 72, options?: RequestOptions) {
    return get<{ window_hours?: number; rows: NewsSecurityRow[]; note_ja?: string }>(
      `/news/securities?${toQuery({ hours })}`,
      options,
    );
  },
  status() {
    return get<NewsStatus>('/news/status');
  },
};
