/** 后端契约类型（与 FastAPI 路由一一对应；缺失字段一律 null，UI 渲染 '—'）。 */

export interface IndexSummary {
  index_code: string;
  name: string;
  trade_date: string | null;
  close: number | null;
  change_pct: number | null;
  return_20d: number | null;
  return_63d: number | null;
  sparkline: number[];
}

export interface SectorStrength {
  sector33_code: string;
  sector33_name: string;
  member_count: number;
  median_return_1d: number | null;
  median_return_20d: number | null;
  leaders: { canonical_code: string; name_ja: string | null; return_1d: number | null }[];
}

export interface MarketOverview {
  version: string;
  data_through: string | null;
  indices: IndexSummary[];
  breadth: {
    advancers: number | null;
    decliners: number | null;
    unchanged: number | null;
    new_highs_252: number | null;
    total_turnover_value: number | null;
  };
  sectors: SectorStrength[];
  short_selling: { trade_date: string; market_short_ratio: number } | null;
}

export interface SearchResult {
  canonical_code: string;
  display_code: string;
  name_ja: string | null;
  name_en: string | null;
  market_name: string | null;
  sector33_name: string | null;
}

export interface StockBar {
  trade_date: string;
  open: number | null;
  high: number | null;
  low: number | null;
  close: number | null;
  adj_open: number | null;
  adj_high: number | null;
  adj_low: number | null;
  adj_close: number | null;
  volume: number | null;
  turnover_value: number | null;
  adjustment_factor: number | null;
}

export interface FinancialSummaryView {
  disclosed_date: string | null;
  disclosed_time: string | null;
  disclosure_number: string | null;
  type_of_document: string | null;
  period_type: string | null;
  period_start: string | null;
  period_end: string | null;
  fiscal_year_end: string | null;
  sales: number | null;
  operating_profit: number | null;
  ordinary_profit: number | null;
  net_profit: number | null;
  eps: number | null;
  equity_ratio: number | null;
  bps: number | null;
  forecast_sales: number | null;
  forecast_operating_profit: number | null;
  forecast_ordinary_profit: number | null;
  forecast_net_profit: number | null;
  forecast_eps: number | null;
  dividend_annual: number | null;
  forecast_dividend_annual: number | null;
  payout_ratio_annual: number | null;
  nc_sales: number | null;
  nc_operating_profit: number | null;
  is_consolidated: boolean;
  forecast_label: string;
}

export interface StockOverview {
  version: string;
  security: {
    canonical_code: string;
    display_code: string;
    name_ja: string | null;
    name_en: string | null;
    market_code: string | null;
    market_name: string | null;
    sector17_name: string | null;
    sector33_code: string | null;
    sector33_name: string | null;
    scale_category: string | null;
    margin_name: string | null;
    active: number | null;
    delisted_date: string | null;
  };
  quote: {
    trade_date: string | null;
    close: number | null;
    adj_close: number | null;
    change_pct: number | null;
    turnover_value: number | null;
    volume: number | null;
  };
  financials: { summaries: FinancialSummaryView[]; single_quarters: Record<string, unknown>[] };
  earnings: Record<string, unknown>[];
  margin_interest: MarginInterestRow[];
  margin_alerts: Record<string, unknown>[];
  short_positions: ShortPositionRow[];
  radar_events: RadarEvent[];
  technical: TechnicalStructure | null;
}

export interface SwingPoint {
  trade_date: string;
  price: number | null;
}

export interface TechnicalStructure {
  base: BaseStructure | null;
  price_action: {
    status: string;
    score: number | null;
    structure: string;
    structure_label: string;
    swing_highs: SwingPoint[];
    swing_lows: SwingPoint[];
    resistance: number | null;
    support: number | null;
    resistance_dist_pct: number | null;
    support_dist_pct: number | null;
    patterns: string[];
    pattern_labels: string[];
    spring: boolean;
    upthrust: boolean;
    tags: string[];
  };
  vol_price: {
    status: string;
    setup_type: string;
    setup_label: string;
    range_compression: number | null;
    turnover_range_ratio: number | null;
    clv_mean: number | null;
    up_down_turnover_ratio: number | null;
    obv_slope: number | null;
    effort: number | null;
    result: number | null;
    breakout_quality_adjustment: number;
    false_breakout_risk: number;
    tags: string[];
  };
  technicals: {
    rsi14: number | null;
    rsi_score: number | null;
    macd: { histogram: number | null; direction_pct: number | null };
    trend_efficiency_63d: number | null;
    ma50_slope_pct_21d: number | null;
    return_stability_20d: number | null;
    range_position_60d: number | null;
    range_persistence_fast: number | null;
    range_persistence_slow: number | null;
  };
  chart_overlays: {
    swing_highs: SwingPoint[];
    swing_lows: SwingPoint[];
    resistance_high?: number | null;
    resistance_low?: number | null;
    support_low?: number | null;
    invalidation_price?: number | null;
    base_start?: string | null;
    base_end?: string | null;
  };
}

export interface MarginInterestRow {
  application_date: string;
  short_total: number | null;
  long_total: number | null;
  short_standardized: number | null;
  long_standardized: number | null;
  issue_type: string | null;
}

export interface ShortPositionRow {
  disclosed_date: string;
  calculated_date: string;
  holder_name: string | null;
  short_position_ratio: number | null;
  previous_ratio: number | null;
}

export interface ScorePack {
  score: number | null;
  confidence: number;
  status: string;
  missing?: string[];
}

export interface RadarScores {
  score_version?: string;
  trend_quality?: ScorePack;
  base_quality?: ScorePack;
  breakout_confirmation?: ScorePack;
  relative_strength?: ScorePack;
  participation?: ScorePack;
  liquidity?: ScorePack;
  breakout_quality?: ScorePack;
  sector_fit?: number | null;
  market_fit?: number | null;
  data_confidence?: number | null;
  chase_risk?: number | null;
  crowding_risk?: number | null;
  alert_priority?: ScorePack;
}

export interface BaseStructure {
  pivot_id?: string | null;
  pivot_price: number | null;
  resistance_low: number | null;
  resistance_high: number | null;
  support_low: number | null;
  support_high?: number | null;
  invalidation_price: number | null;
  base_start: string | null;
  base_end: string | null;
  resistance_touches: number | null;
  quality: number | null;
  base_duration_days?: number | null;
  metrics?: Record<string, number | null>;
}

export interface EventStructure {
  base: BaseStructure | null;
  structure: string | null;
  structure_label: string | null;
  price_action_score: number | null;
  pattern_labels: string[];
  spring: boolean;
  upthrust: boolean;
  setup_type: string | null;
  setup_label: string | null;
  vpm_tags: string[];
  rsi14: number | null;
  trend_efficiency_63d: number | null;
}

export interface RadarEvent {
  event_id: string;
  canonical_code: string;
  display_code: string;
  name_ja?: string | null;
  sector33_name?: string | null;
  market_name?: string | null;
  signal_type: string;
  state: string;
  discovered_date: string;
  state_changed_date: string;
  last_scanned_date: string;
  pivot_price: number | null;
  trigger_price: number | null;
  alert_priority: number | null;
  scores: RadarScores;
  snapshot: Record<string, number | string | boolean | null>;
  structure?: EventStructure | null;
  transitions?: { date: string; from: string | null; to: string; reason: string }[];
}

export interface RadarCurrent {
  scan_date: string | null;
  granularity?: string;
  events: RadarEvent[];
  note?: string;
}

export interface ScreenerRow {
  canonical_code: string;
  trade_date: string;
  market_code: string | null;
  sector33_code: string | null;
  close: number | null;
  turnover_value: number | null;
  avg_turnover_20d: number | null;
  turnover_ratio: number | null;
  return_1d: number | null;
  return_5d: number | null;
  return_20d: number | null;
  return_63d: number | null;
  pct_from_high_252: number | null;
  ma25_gap_pct: number | null;
  ma75_gap_pct: number | null;
  ma200_gap_pct: number | null;
  ma_alignment: number | null;
  rs_topix_63d: number | null;
  rs_sector_63d: number | null;
  volatility_contraction: number | null;
  drawdown_63d: number | null;
  margin_long_short_ratio: number | null;
  metrics: {
    name_ja?: string | null;
    sector33_name?: string | null;
    market_name?: string | null;
    radar_state?: string | null;
  };
}

export interface ScreenerResponse {
  version: string;
  trade_date: string | null;
  total: number;
  rows: ScreenerRow[];
}

export interface WatchlistItem {
  canonical_code: string;
  display_code: string;
  note: string | null;
  marked_important: boolean;
  added_at: string | null;
  name_ja: string | null;
  sector33_name: string | null;
  market_name: string | null;
  quote: {
    trade_date: string | null;
    close: number | null;
    change_pct: number | null;
    turnover_value: number | null;
  } | null;
}

export interface EarningsCalendarItem {
  canonical_code: string;
  display_code: string;
  company_name: string | null;
  announcement_date: string | null;
  fiscal_year_end: string | null;
  fiscal_quarter: string | null;
  sector_name: string | null;
  section: string | null;
  in_watchlist: boolean;
}

export interface EarningsRecentItem {
  canonical_code: string;
  display_code: string;
  name_ja: string | null;
  sector33_name: string | null;
  disclosed_date: string | null;
  disclosed_time: string | null;
  period_type: string | null;
  fiscal_year_end: string | null;
  type_of_document: string | null;
  is_forecast_revision: boolean | null;
  sales: number | null;
  operating_profit: number | null;
  net_profit: number | null;
  eps: number | null;
  forecast_operating_profit: number | null;
  forecast_direction: 'upward' | 'downward' | 'unchanged' | null;
  forecast_label: string;
  in_watchlist: boolean;
}

export interface DatasetStatus {
  key: string;
  endpoint: string;
  status: 'enabled' | 'planned' | 'unavailable';
  cadence: string;
  history_years: number | null;
  note_ja: string | null;
  last_success_at?: string | null;
  last_error_code?: string | null;
  data_through?: string | null;
  rows_total?: number | null;
  freshness?: string | null;
  backfill_pending?: number | null;
}

export interface DataStatusResponse {
  version: string;
  provider: string;
  plan: string;
  api_key_configured: boolean;
  market_timezone: string;
  core_database_ready?: boolean;
  datasets: DatasetStatus[];
  intraday: { enabled: boolean; note_ja?: string };
  worker?: {
    healthy: boolean;
    tasks?: Record<string, { status: string; last_success_at?: string | null; error_code?: string | null }>;
    degraded_tasks?: string[];
  } | null;
}

export interface IntradayBar {
  trade_date: string;
  bar_time: string;
  open: number | null;
  high: number | null;
  low: number | null;
  close: number | null;
  volume: number | null;
  turnover_value: number | null;
}

export interface IntradayChart {
  canonical_code: string;
  display_code: string;
  interval: '1m' | '5m' | '60m';
  available: boolean;
  availability?: string;
  reason?: 'plan_not_included' | 'not_fetched';
  note_ja?: string;
  days?: string[];
  data_through: string | null;
  bars: IntradayBar[];
}

export interface AccessStatus {
  mode: 'private_network' | 'password';
  is_owner: boolean;
  password_configured: boolean;
}

export interface SettingsView {
  jquants_configured: boolean;
  openai_configured: boolean;
  access_mode: string;
  radar_enabled: boolean;
  news_mode: string;
  app_version: string;
  app_commit: string;
}
