/** 领域 API 模块：registry 走共享注册表，其余直连。 */

import { del, get, patch as patchVerb, post, toQuery } from './client.ts';
import { registryGet } from './queryRegistry.ts';
import type {
  AccessStatus,
  ResearchReport,
  DataStatusResponse,
  EarningsCalendarItem,
  EarningsRecentItem,
  EarningsUpcomingResponse,
  EconCalendarResponse,
  IntradayChart,
  TickView,
  MarketOverview,
  IntradayQuotesResponse,
  IntradaySectorsResponse,
  IntradayOverlayResponse,
  SectorMemberSort,
  SectorMembersView,
  MarketRegime,
  NewsFeedResponse,
  NewsHotspotGroup,
  NewsSecurityRow,
  NewsStatus,
  RadarCurrent,
  RadarEvent,
  ScreenerResponse,
  ShortMonitorDetail,
  ShortMonitorEvents,
  ShortMonitorOverview,
  ShortMonitorRankings,
  SearchResult,
  SettingsView,
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
    return get('/quotes/sectors/intraday');
  },
  sectorMembers(code: string, sort: SectorMemberSort, limit = 12): Promise<SectorMembersView> {
    return get(`/market/sectors/${encodeURIComponent(code)}/members?${toQuery({ sort, limit })}`);
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
  intradayChart(code: string, interval: '1m' | '5m' | '60m'): Promise<IntradayChart> {
    return get(`/stocks/${encodeURIComponent(code)}/chart?${toQuery({ interval })}`);
  },
  intradayQuotes(codes: string[]): Promise<IntradayQuotesResponse> {
    return get(`/quotes/intraday?${toQuery({ codes: codes.join(',') })}`);
  },
  tickView(code: string): Promise<TickView> {
    return get(`/stocks/${encodeURIComponent(code)}/ticks`);
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
  calendar(start?: string, end?: string): Promise<{ coverage_note: string; items: EarningsCalendarItem[] }> {
    const query = toQuery({ start, end });
    return query
      ? get(`/earnings/calendar?${query}`)
      : registryGet('/earnings/calendar');
  },
  upcoming(): Promise<EarningsUpcomingResponse> {
    return get('/earnings/upcoming');
  },
  recent(days = 7): Promise<{ items: EarningsRecentItem[] }> {
    return days === 7 ? registryGet('/earnings/recent') : get(`/earnings/recent?${toQuery({ days })}`);
  },
};

export const researchApi = {
  report(runId?: string): Promise<ResearchReport> {
    return get(runId ? `/research/report?run_id=${encodeURIComponent(runId)}` : '/research/report');
  },
};

export const quotesApi = {
  overlay(scope: 'radar' | 'screener', limit = 200): Promise<IntradayOverlayResponse> {
    return get(`/quotes/overlay?${toQuery({ scope, limit })}`);
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

export const shortMonitorApi = {
  overview(date?: string): Promise<ShortMonitorOverview> {
    return get(date ? `/short-monitor/overview?${toQuery({ date })}` : '/short-monitor/overview');
  },
  rankings(params: {
    view?: string;
    date?: string;
    states?: string;
    flags?: string;
    markets?: string;
    sectors?: string;
    codes?: string;
    min_confidence?: number;
    min_turnover?: number;
    min_score?: number;
    order_by?: string;
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

export const settingsApi = {
  get(): Promise<SettingsView> {
    return registryGet('/settings');
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
  me() {
    return get<{ logged_in: boolean; username: string | null }>('/account/me');
  },
};

export const workerApi = {
  status() {
    return registryGet<Record<string, unknown>>('/worker/status');
  },
  trigger(actionType: string, body?: { code?: string }) {
    return post<{ action_type: string; action_id: number | null; status: string; duplicate: boolean }>(
      `/worker/actions/${encodeURIComponent(actionType)}`,
      body,
    );
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
  scan(params: StrengthScanParams = {}): Promise<StrengthScanResponse> {
    return get(`/strength/scan?${toQuery({ ...params })}`);
  },
  market(): Promise<{ trade_date: string; built_at: string; market_regime: MarketRegime; universe_count: number }> {
    return get('/strength/market');
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
  securities(hours = 72) {
    return get<{ window_hours?: number; rows: NewsSecurityRow[]; note_ja?: string }>(
      `/news/securities?${toQuery({ hours })}`,
    );
  },
  status() {
    return get<NewsStatus>('/news/status');
  },
  econCalendar(start?: string, end?: string) {
    return get<EconCalendarResponse>(`/news/econ-calendar?${toQuery({ start, end })}`);
  },
};
