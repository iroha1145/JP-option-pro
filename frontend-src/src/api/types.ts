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
  /** 业种内上涨股占比（0..1）：热力砖底端细条 */
  advancers_share: number | null;
  leaders: { canonical_code: string; name_ja: string | null; return_1d: number | null }[];
}

/** 板块最热门个股（美版「板块 IV 横截面排名」的日股替代） */
export type SectorMemberSort = 'turnover' | 'heat' | 'change';

export interface SectorMemberRow {
  canonical_code: string;
  display_code: string;
  name_ja: string | null;
  market_name: string | null;
  radar_state: string | null;
  close: number | null;
  return_1d: number | null;
  return_20d: number | null;
  turnover_value: number | null;
  turnover_ratio: number | null;
  avg_turnover_20d: number | null;
  pct_from_high_252: number | null;
  /** 業種相対は 20 日と 63 日で別物。以前は 20 日の値を 63 日の名前で運んでいた。 */
  rs_sector_20d?: number | null;
  rs_sector_63d: number | null;
  turnover_share: number | null;
}

export interface SectorMembersView {
  version: string;
  sector33_code: string;
  sector33_name: string;
  trade_date: string | null;
  sort: SectorMemberSort;
  member_count: number;
  sector_turnover_value: number | null;
  rows: SectorMemberRow[];
}

/** 遅延ザラ場気配（Yahoo・非公式・表示専用）。公式値と混ぜないこと。 */
export interface IntradayQuote {
  key: string;
  symbol: string;
  price: number;
  previous_close: number | null;
  change_pct: number | null;
  as_of_epoch: number | null;
  source: string;
}

/** 供給元の素性。値の意味はこれで決まるので、画面はベンダ名を焼き込まない。 */
export interface QuoteSourceEnvelope {
  source: string;
  /** realtime | delayed | end_of_day | unknown */
  delay_class?: string;
  is_official?: boolean;
  is_realtime?: boolean;
  source_detail?: string | null;
  delayed?: boolean;
  delayed_minutes?: number;
}

export interface IntradayQuotesResponse extends QuoteSourceEnvelope {
  version: string;
  enabled: boolean;
  quotes: Record<string, IntradayQuote>;
  indices?: Record<string, IntradayQuote & { name: string }>;
}

export interface IntradaySectorsResponse extends QuoteSourceEnvelope {
  enabled: boolean;
  universe?: number;
  quoted?: number;
  sectors: { sector33_code: string; sector33_name: string; median_return_1d: number; advancers_share: number; covered: number }[];
}

/** 夜間断面 × 遅延気配のオーバーレイ（再スキャンではない） */
export interface IntradayOverlayRow {
  live_price: number;
  pivot_price?: number;
  pivot_distance_pct?: number;
  above_pivot?: boolean;
  live_change_pct?: number;
  live_pct_from_high_252?: number | null;
}

export interface IntradayOverlayResponse extends QuoteSourceEnvelope {
  enabled: boolean;
  scope: 'radar' | 'screener';
  requested?: number;
  quoted?: number;
  above_pivot_count?: number;
  rows: Record<string, IntradayOverlayRow>;
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
  short_interest: ShortInterestSummary | null;
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

/** 空売り残高: 2週間の変化一覧 + 報告義務中の合計 */
export interface ShortInterestChange {
  holder_name: string | null;
  calculated_date: string;
  disclosed_date: string | null;
  ratio: number | null;
  shares: number | null;
  units: number | null;
  previous_ratio: number | null;
  delta: number | null;
  /** new | increased | decreased | below_threshold | closed */
  kind: string;
  state: string;
}

export interface ShortInterestSummary {
  as_of: string | null;
  baseline_date: string | null;
  window_trading_days: number;
  /** 報告義務が続いている保有者だけの合計。閾値割れの最終報告は含まない。 */
  reporting_total: number | null;
  /** 同じ保有者集合の株数合計。1 件でも欠ければ null（欠損を 0 で埋めない）。 */
  reporting_shares: number | null;
  reporting_holders: number;
  below_threshold_holders: number;
  closed_holders: number;
  baseline_total: number | null;
  change: number | null;
  reporting_threshold: number;
  changes: ShortInterestChange[];
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
  rs_sector_20d?: number | null;
  rs_sector_63d: number | null;
  /** none | precaution | daily_publication | restricted | severe | unknown */
  regulation_level?: string | null;
  regulation_severity?: number | null;
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
  reason?: 'plan_not_included' | 'not_fetched' | 'fetching';
  queued?: boolean;
  note_ja?: string;
  days?: string[];
  data_through: string | null;
  bars: IntradayBar[];
}

/** ティック（歩み値）— サーバ側で秒バケットに間引いたチャート点 + 直近テープ */
export interface TickPoint {
  t: string; // HH:MM:SS（バケット開始）
  price: number; // バケット内の最終価格
  high: number;
  low: number;
  volume: number;
}

export interface TickTapeRow {
  time: string;
  price: number | null;
  volume: number | null;
  direction: 'up' | 'down' | 'flat';
}

export interface TickAnalytics {
  available: boolean;
  tick_count?: number;
  vwap: { vwap: number | null; last_price: number | null; deviation_pct: number | null; total_volume?: number; series: { t: string; vwap: number; price: number }[] } | null;
  large_prints: { threshold: number | null; median_size: number | null; count: number; volume_share: number | null; rows: { time: string; price: number | null; volume: number | null }[] } | null;
  volume_profile: { low: number | null; high: number | null; poc: number | null; total_volume?: number; buckets: { price_low: number; price_high: number; volume: number }[] } | null;
  auctions: {
    day_volume: number;
    opening: AuctionPrint | null;
    closing: AuctionPrint | null;
    afternoon_open: AuctionPrint | null;
  } | null;
  sessions: { morning: { prints: number; volume: number }; afternoon: { prints: number; volume: number } } | null;
}

export interface AuctionPrint {
  time: string;
  price: number | null;
  volume: number;
  prints: number;
  day_volume_share: number | null;
}

export interface TickView {
  analytics?: TickAnalytics;
  canonical_code: string;
  display_code: string;
  available: boolean;
  availability?: string;
  reason?: 'plan_not_included' | 'not_fetched' | 'fetching';
  queued?: boolean;
  note_ja?: string;
  trade_date: string | null;
  tick_count: number;
  truncated?: boolean;
  fetched_at?: string;
  bucket_seconds?: number;
  points: TickPoint[];
  tape: TickTapeRow[];
}

/* ---------------- 决算日历（高密度视图） ---------------- */

/** released=已公布（带实绩）/ confirmed=官方確定（仅次一交易日）/ estimated=目安（前年同期推导）/ tbd=未定 */
export interface EarningsUpcomingItem {
  canonical_code: string;
  display_code: string;
  name_ja: string | null;
  sector33_name: string | null;
  date: string | null;
  status: 'released' | 'confirmed' | 'estimated' | 'tbd';
  confirmed: boolean;
  estimate_basis?: string;
  period_type: string | null;
  quarter_label: string | null;
  fiscal_year_end: string | null;
  close: number | null;
  change_pct: number | null;
  avg_turnover_20d: number | null;
  in_watchlist: boolean;
  radar_state: string | null;
  featured: boolean;
  forecast: {
    metric: 'operating_profit' | 'net_profit';
    forecast_value: number | null;
    prior_fy_value: number | null;
    direction: 'upward' | 'downward' | 'unchanged' | null;
    as_of: string | null;
  } | null;
  actual?: {
    sales: number | null;
    operating_profit: number | null;
    net_profit: number | null;
    disclosed_time: string | null;
    is_revision: boolean;
  };
}

export interface EarningsUpcomingResponse {
  coverage_note: string;
  today: string;
  window_start: string;
  window_end: string;
  counts: { released: number; confirmed: number; estimated: number; tbd: number };
  items: EarningsUpcomingItem[];
  tbd_items: EarningsUpcomingItem[];
}

/* ---------------- 强度扫描（美版 Strength Radar 的日股移植） ---------------- */

export interface StrengthStructure {
  price_action: {
    structure?: string | null;
    structure_label?: string | null;
    pattern_labels?: string[];
    spring?: boolean;
    upthrust?: boolean;
  };
  vol_price: {
    setup_type?: string | null;
    setup_label?: string | null;
    breakout_quality_adjustment?: number | null;
    false_breakout_risk?: number | null;
    tags?: string[];
  };
  technicals: {
    rsi14?: number | null;
    macd_direction_pct?: number | null;
    trend_efficiency_63d?: number | null;
    ma50_slope_pct_21d?: number | null;
  };
}

export interface StrengthRow {
  canonical_code: string;
  display_code: string;
  name_ja: string | null;
  sector33_code: string | null;
  sector33_name: string | null;
  market_name: string | null;
  close: number | null;
  change_pct: number | null;
  intrinsic_score: number | null;
  /** リスク調整後（並べ替えに使われる値）。raw − penalty。 */
  ranking_score: number | null;
  /** 減点前の素点 */
  raw_ranking_score?: number | null;
  /** 明示的な最終値（ranking_score と同値。意図を読めるように併記） */
  final_ranking_score?: number | null;
  market_fit_score: number | null;
  profile_fit_score: number | null;
  confidence: number | null;
  ranking_confidence: number | null;
  score_short: number | null;
  score_mid: number | null;
  score_long: number | null;
  trend_score: number | null;
  breakout_quality_score: number | null;
  price_action_score: number | null;
  global_rank_percentile: number | null;
  sector_rank_percentile: number | null;
  avg_turnover_20d: number | null;
  turnover_ratio: number | null;
  atr_pct: number | null;
  ath_proximity: number | null;
  rs_topix_63d: number | null;
  ma_alignment_pct: number | null;
  risk_penalty: number | null;
  classification: string | null;
  tags: string[];
  reasons: string[];
  warnings: string[];
  selected_view_rank: number | null;
  families: Record<string, number | null>;
  effective_weights: Record<string, number>;
  missing_families: string[];
  structure: StrengthStructure;
}

export interface MarketRegime {
  score: number | null;
  label: string | null;
  confidence: number | null;
  status: string;
  dims: {
    index_trend: number | null;
    momentum: number | null;
    breadth: number | null;
    volume: number | null;
    risk_appetite: number | null;
    risk_on_spread: number | null;
  };
  spread_label: string | null;
  warnings: string[];
  universe_size?: number;
}

export interface TierDistribution {
  S: number; A: number; B: number; C: number; D: number;
  unscored: number; scored: number; total: number;
}

export interface StrengthScanResponse {
  trade_date: string;
  built_at: string;
  score_version: string;
  params: Record<string, unknown>;
  market_regime: MarketRegime;
  universe_count: number;
  screened_count: number;
  matched_count: number;
  tier_distribution: TierDistribution;
  rows: StrengthRow[];
}

export interface StrengthProfilesMeta {
  timeframes: string[];
  profiles: { id: string; name: string; description: string }[];
  presets: { id: string; name: string; profile: string; min_score: number | null; description: string }[];
  sectors: { id: string; name: string }[];
  family_weights: Record<string, number>;
}

/** AI 分析的受影响股票：只有代码与理由，不含方向预测（v2 起产品移除）。 */
export interface NewsAffected {
  code: string;
  reason_zh: string | null;
}

export interface NewsItem {
  news_id: string;
  source: string | null;
  source_url: string | null;
  published_at: string | null;
  source_language: string | null;
  original_title: string | null;
  original_summary: string | null;
  translated_title_ja: string | null;
  summary_ja: string | null;
  analysis_zh: {
    headline: string | null;
    impact: string | null;
    affected: NewsAffected[] | null;
    insufficient_context: boolean | null;
  } | null;
  analysis_state?: 'completed' | 'pending' | 'failed' | 'disabled' | 'none';
  categories: string[];
  securities: { canonical_code: string; display_code: string; name_ja: string | null }[];
  importance: number | null;
  importance_reasons?: string[];
  market_relevance?: string | null;
}

export interface NewsFeedResponse {
  mode: string;
  window_hours?: number;
  items: NewsItem[];
  note_ja?: string;
}

export interface NewsHotspotGroup {
  canonical_code: string;
  display_code: string;
  name_ja: string | null;
  item_count: number;
  max_importance: number | null;
  categories: string[];
  latest: { news_id: string; title: string | null; published_at: string | null } | null;
}

export interface NewsSecurityRow {
  canonical_code: string;
  display_code: string;
  name_ja: string | null;
  news_count: number;
  max_importance: number | null;
  categories: string[];
  latest: { title: string | null; published_at: string | null } | null;
  ai: { analyzed: number } | null;
}

export interface NewsFeedState {
  feed_url: string;
  etag?: string | null;
  last_modified?: string | null;
  last_fetched_at: string | null;
  last_error_code: string | null;
  items_seen: number;
}

export interface NewsStatus {
  mode: string;
  sync_seconds: number;
  window_hours: number;
  entity_aliases: number;
  feeds: NewsFeedState[];
  ai: {
    enabled: boolean;
    openai_configured: boolean;
    translation_target: string;
    analysis_language: string;
    queue: Record<string, number>;
    note_ja: string | null;
  };
}

export interface EconEvent {
  date: string;
  time_jst: string;
  name_ja: string;
  category: string;
  importance: 'high' | 'medium' | 'low';
  organizer: string;
  confirmed: boolean;
  source_url?: string;
  note?: string;
}

export interface EconCalendarResponse {
  coverage_note_ja: string;
  start_date: string;
  end_date: string;
  events: EconEvent[];
}

export interface AccessStatus {
  mode: 'private_network' | 'password';
  is_owner: boolean;
  password_configured: boolean;
  /** 访客账号会话（与美股版共库的账号体系；不授予任何 owner 权限）。 */
  account?: { logged_in: boolean; username: string | null };
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

/** 走步検証レポート（読み取り専用・研究ページ用） */
export interface ResearchBucket {
  bucket: string;
  samples: number;
  median_return: number | null;
  median_excess_topix: number | null;
  hit_rate: number | null;
  median_mfe: number | null;
  median_mae: number | null;
  target_before_stop: number | null;
  /** 標本不足の層も返す。隠すと上位だけ綺麗に見えるため。 */
  reliable: boolean;
}

export interface ResearchWindow {
  train: [string, string];
  test: [string, string];
  horizon_trading_days: number;
  samples: number;
  buckets: ResearchBucket[];
  deciles: ResearchBucket[];
  monotonic: boolean | null;
  decile_monotonic: boolean | null;
  top_bottom_spread: number | null;
}

export interface ResearchReport {
  run_id: string;
  finished_at?: string | null;
  score_version: string;
  replay_version: string;
  signals: number;
  evaluation_dates: number;
  windows: ResearchWindow[];
  summary: {
    windows: number;
    windows_judged: number;
    windows_monotonic: number;
    windows_with_spread?: number;
    windows_positive_spread?: number;
    median_top_bottom_spread?: number | null;
    verdict: 'monotonic' | 'weak' | 'not_monotonic' | 'insufficient_data';
    note: string;
  };
  point_in_time_limits: string[];
}

/* -- 机构空卖行为监控 ------------------------------------------------------
   命名规则与后端一致：只有 `visible` / `reported`，没有 total_short_*。
   J-Quants 的机构空卖报告只覆盖达到公开披露条件的部分。 */

export interface ShortMonitorScores {
  low_position: number | null;
  short_pressure: number | null;
  price_damage: number | null;
  absorption: number | null;
  covering: number | null;
  rotation: number | null;
  catalyst: number | null;
  risk: number | null;
}

export interface ShortMonitorRow {
  canonical_code: string;
  display_code: string;
  name: string | null;
  market_code: string | null;
  market_name: string | null;
  sector33_code: string | null;
  sector33_name: string | null;
  as_of_date: string;
  close: number | null;
  drawdown_52w: number | null;
  price_percentile_252: number | null;
  visible_short_ratio: number | null;
  visible_short_shares: number | null;
  visible_institution_count: number;
  below_threshold_count: number;
  largest_institution_ratio: number | null;
  concentration: number | null;
  ratio_change_5d: number | null;
  ratio_change_20d: number | null;
  shares_change_20d: number | null;
  pressure_adv20_5d: number | null;
  pressure_adv20_20d: number | null;
  visible_days_to_cover: number | null;
  rel_topix_20d: number | null;
  rel_sector_20d: number | null;
  entry_count_20d: number;
  reentry_count_20d: number;
  reduction_count_20d: number;
  threshold_exit_count_20d: number;
  scores: ShortMonitorScores;
  behavior_score: number | null;
  monitor_priority: number | null;
  data_confidence: number | null;
  primary_state: string;
  flags: string[];
  algorithm_version: string | null;
}

export interface ShortMonitorOverview {
  as_of_date: string | null;
  synced_at?: string | null;
  coverage: { covered: number; with_visible_short: number; low_confidence: number } | null;
  states: Record<string, number>;
  note: string;
  algorithm_version?: string;
  score_version?: string;
  /** 门槛与权重是否已通过历史验证。未验证时界面必须说出来。 */
  validated?: { gates: boolean; score: boolean };
}

export interface ShortMonitorRankings {
  as_of_date: string | null;
  view: string;
  order_by: string;
  total: number;
  limit: number;
  offset: number;
  rows: ShortMonitorRow[];
  note: string;
}

export interface ShortMonitorHolder {
  legal_id: string;
  name: string;
  group_name: string | null;
  last_reported_ratio: number | null;
  last_reported_shares: number | null;
  last_position_date: string | null;
  last_published_date: string | null;
  visibility_status: string;
  /** false = 跌破门槛后实际仓位不可见。绝不把线画到 0。 */
  exact_position_known: boolean;
  state_age_trading_days: number | null;
  is_hedge_disclosed: boolean;
  mapping_confidence: number | null;
}

export interface ShortMonitorHistoryPoint {
  as_of_date: string;
  visible_short_ratio: number | null;
  visible_short_shares: number | null;
  visible_institution_count: number;
  below_threshold_count: number;
  behavior_score: number | null;
  primary_state: string;
}

export interface ShortMonitorExplanation {
  state: string;
  state_label: string;
  lines: string[];
  caveat: string | null;
}

export interface ShortMonitorDetail extends ShortMonitorRow {
  components: Record<string, unknown>;
  holders: ShortMonitorHolder[];
  history: ShortMonitorHistoryPoint[];
  explanation: ShortMonitorExplanation;
  note: string;
}

export interface ShortMonitorEvent {
  event_id: string;
  institution: string;
  legal_id: string;
  group_id: string | null;
  position_date: string;
  published_date: string;
  effective_trade_date: string;
  short_ratio: number | null;
  short_shares: number | null;
  previous_ratio: number | null;
  ratio_delta: number | null;
  event_type: string;
  visibility_status: string;
  correction_status: string;
  is_hedge_disclosed: boolean;
  mapping_confidence: number | null;
}

export interface ShortMonitorEvents {
  canonical_code: string;
  total: number;
  limit: number;
  offset: number;
  events: ShortMonitorEvent[];
  note: string;
}
