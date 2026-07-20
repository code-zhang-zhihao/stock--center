export type SectorType = 'concept' | 'industry';
export type SectorProvider = 'tushare' | 'akshare' | 'all';

export interface BrowseSector {
  sector_code: string;
  sector_name: string;
  sector_type: SectorType;
  source: string | null;
  last_synced_at: string | null;
  component_count: number;
}

export interface BrowseSectorPage {
  items: BrowseSector[];
  total: number;
  page: number;
  page_size: number;
}

export interface BrowseSectorStock {
  stock_code: string;
  stock_name: string | null;
  raw_stock_name: string | null;
  stock_exists: boolean;
  exchange: string | null;
  industry: string | null;
  area: string | null;
  status: string | null;
  weight: number | null;
  component_source: string | null;
  linked_at: string | null;
}

export interface BrowseSectorStocks {
  sector: Omit<BrowseSector, 'component_count'>;
  items: BrowseSectorStock[];
  total: number;
  page: number;
  page_size: number;
}

export interface SectorAnalysisOverview {
  sector: BrowseSector;
  raw_code: string;
  taxonomy: string;
}

export interface SectorAnalysisBar {
  trade_date: string;
  open: number | null;
  high: number | null;
  low: number | null;
  close: number | null;
  pre_close: number | null;
  change: number | null;
  pct_change: number | null;
  volume: number | null;
  amount: number | null;
}

export interface SectorMoneyFlowPoint {
  trade_date: string;
  ts_code: string | null;
  sector_name: string | null;
  lead_stock: string | null;
  close_price: number | null;
  pct_change: number | null;
  company_num: number | null;
  lead_close_price: number | null;
  lead_pct_change: number | null;
  net_buy_amount: number | null;
  net_sell_amount: number | null;
  net_amount: number | null;
}

export interface SectorAnalysisSeries<T> {
  sector: BrowseSector;
  source: string;
  items: T[];
  total: number;
  provider?: {
    token_fingerprint?: string | null;
    endpoint_url?: string | null;
    row_count?: number;
  };
}

export interface SectorLeader {
  trade_date: string;
  stock_code: string | null;
  stock_name: string;
  close_price: number | null;
  pct_change: number | null;
  sector_pct_change: number | null;
}

export interface SectorLeaderPage {
  sector: BrowseSector;
  items: SectorLeader[];
  total: number;
}

export interface SectorDashboardItem extends BrowseSector {
  rank: number | null;
  main_net_inflow: number | null;
  main_net_ratio: number | null;
  change_pct: number | null;
  lead_stock: string | null;
  lead_stock_pct_change: number | null;
  hot: number | null;
  hot_rank: number | null;
}

export interface SectorDashboardData {
  source: string;
  updated_at: string;
  warnings: string[];
  items: SectorDashboardItem[];
}

export interface StockSearchItem {
  stock_code: string;
  stock_name: string;
  market: string;
  exchange: string | null;
  list_date: string | null;
  delist_date: string | null;
  status: string;
  industry: string | null;
  area: string | null;
}

export interface StockAnalysisSearchResult {
  items: StockSearchItem[];
  total: number;
}

export interface StockSectorTag {
  sector_code: string;
  sector_name: string;
  sector_type: SectorType;
  source: string | null;
  component_source: string | null;
}

export interface StockDailyBasic {
  stock_code: string;
  trade_date: string;
  source: string;
  close_price: number | null;
  turnover_rate: number | null;
  turnover_rate_f: number | null;
  volume_ratio: number | null;
  pe: number | null;
  pe_ttm: number | null;
  pb: number | null;
  ps: number | null;
  ps_ttm: number | null;
  dv_ratio: number | null;
  dv_ttm: number | null;
  total_mv: number | null;
  circ_mv: number | null;
  limit_status: number | null;
}

export interface StockDailyBar {
  stock_code: string;
  trade_date: string;
  source: string;
  adjust_mode?: string;
  open_price: number | null;
  high_price: number | null;
  low_price: number | null;
  close_price: number | null;
  pre_close_price?: number | null;
  change_amount?: number | null;
  change_pct?: number | null;
  volume_hand: number | null;
  volume_share?: number | null;
  amount_yuan: number | null;
  turnover_rate?: number | null;
}

export interface StockDailyChartBar extends StockDailyBar {
  ma5: number | null;
  ma10: number | null;
  ma20: number | null;
  ma30: number | null;
  ma60: number | null;
}

export interface StockMinuteBar {
  stock_code: string;
  trade_date?: string;
  bar_time: string;
  interval: string;
  source: string;
  price: number | null;
  avg_price: number | null;
  volume_hand: number | null;
  volume_share?: number | null;
  amount_yuan: number | null;
}

export interface StockQuote {
  stock_code: string;
  quote_time: string;
  source: string;
  snapshot_kind?: string;
  last_price: number | null;
  pre_close_price: number | null;
  change_amount: number | null;
  change_pct: number | null;
  open_price: number | null;
  high_price: number | null;
  low_price: number | null;
  volume_hand: number | null;
  amount_yuan: number | null;
  order_book?: Record<string, unknown>;
}

export interface TechnicalSnapshot {
  stock_code: string;
  snapshot_time: string;
  source: string;
  last_price: number | null;
  change_pct: number | null;
  intraday_strength: number | null;
  volume_score: number | null;
  trend_score: number | null;
  factor_payload: Record<string, unknown>;
}

export interface StockAnalysisOverview {
  stock: StockSearchItem;
  daily_basic: StockDailyBasic | null;
  latest_daily_bar: StockDailyBar | null;
  technical_snapshot: TechnicalSnapshot | null;
  sectors: {
    concepts: StockSectorTag[];
    industries: StockSectorTag[];
    items: StockSectorTag[];
  };
}

export interface StockAnalysisRealtime {
  stock_code: string;
  quote: StockQuote | null;
  minute_bars: StockMinuteBar[];
  minute_meta?: {
    status?: string;
    updated_at?: string;
    bar_count?: number;
    features?: Record<string, unknown>;
  };
  meta: {
    query_mode: string;
    resolved_source: string | null;
    attempted_engines: string[];
    fallback_used: boolean;
    persisted: boolean;
    runtime_enabled?: boolean;
    market_session?: boolean;
    cache_status?: 'hit' | 'on_demand' | 'cooldown' | 'unavailable' | string;
    errors: string[];
  };
}

export interface StockAnalysisSeries<T> {
  stock_code: string;
  items: T[];
  total: number;
  source: string;
}

export interface StockAnalysisMinuteSeries extends StockAnalysisSeries<StockMinuteBar> {
  trade_date: string | null;
  reference_price: number | null;
}

export interface StockDailyFactor {
  stock_code: string;
  trade_date: string;
  source: string;
  ma5: number | null;
  ma10: number | null;
  ma20: number | null;
  ma30: number | null;
  ma60: number | null;
  return_1d: number | null;
  amplitude: number | null;
  volume_ratio: number | null;
  amount_ratio: number | null;
  volatility_20d: number | null;
  close_position: number | null;
  features: Record<string, unknown>;
}

export interface StockMinuteFactor {
  stock_code: string;
  trade_date: string;
  bar_time: string;
  source: string;
  vwap: number | null;
  minute_return: number | null;
  volume_spike_ratio: number | null;
  intraday_strength: number | null;
  features: Record<string, unknown>;
}

export interface StockTechnicalFactor {
  stock_code: string;
  trade_date: string;
  source: string;
  factors: Record<string, unknown>;
}

export interface StockChipPerf {
  stock_code: string;
  trade_date: string;
  source: string;
  his_low: number | null;
  his_high: number | null;
  cost_5pct: number | null;
  cost_15pct: number | null;
  cost_50pct: number | null;
  cost_85pct: number | null;
  cost_95pct: number | null;
  weight_avg: number | null;
  winner_rate: number | null;
}

export interface StockAnalysisFactors {
  stock_code: string;
  daily_factors: StockDailyFactor[];
  minute_factors: StockMinuteFactor[];
  minute_factor_trade_date?: string | null;
  technical_snapshots: TechnicalSnapshot[];
  technical_factors: StockTechnicalFactor[];
  chip_perf: StockChipPerf[];
  latest: {
    daily_factor: StockDailyFactor | null;
    technical_factor: StockTechnicalFactor | null;
    chip_perf: StockChipPerf | null;
    technical_snapshot: TechnicalSnapshot | null;
  };
  missing: {
    technical_factor: boolean;
    chip_perf: boolean;
  };
}

export interface StockFundFlow {
  stock_code: string;
  trade_date: string;
  source: string;
  main_net_inflow: number | null;
  main_net_ratio: number | null;
  big_order_net_inflow: number | null;
  big_order_net_ratio: number | null;
  super_large_net_inflow: number | null;
  medium_net_inflow: number | null;
  small_net_inflow: number | null;
  small_buy_amount: number | null;
  small_sell_amount: number | null;
  medium_buy_amount: number | null;
  medium_sell_amount: number | null;
  large_buy_amount: number | null;
  large_sell_amount: number | null;
  super_large_buy_amount: number | null;
  super_large_sell_amount: number | null;
  close_price: number | null;
  change_pct: number | null;
  rank: number | null;
}

export interface StockFundFlowSeries {
  stock_code: string;
  items: StockFundFlow[];
  latest: StockFundFlow | null;
  total: number;
  source: string;
}

export interface StockLimitEvent {
  stock_code: string;
  trade_date: string;
  event_type: string;
  source: string;
  close_price: number | null;
  limit_price: number | null;
  first_time: string | null;
  last_time: string | null;
  open_count: number | null;
  turnover_amount: number | null;
}

export interface StockLhbEvent {
  stock_code: string;
  stock_name: string | null;
  trade_date: string;
  source: string;
  reason: string;
  close_price: number | null;
  change_pct: number | null;
  turnover_amount: number | null;
  net_buy_amount: number | null;
  buy_amount: number | null;
  sell_amount: number | null;
}

export interface StockLhbSeat {
  stock_code: string;
  trade_date: string;
  source: string;
  side: string;
  seat_name: string;
  buy_amount: number | null;
  sell_amount: number | null;
  net_amount: number | null;
  rank: number | null;
}

export interface StockAnnouncement {
  stock_code: string;
  stock_name: string | null;
  title: string;
  category: string | null;
  published_at: string;
  url: string | null;
  source: string;
}

export interface StockAnalysisEvents {
  stock_code: string;
  limit_events: StockLimitEvent[];
  lhb_events: StockLhbEvent[];
  lhb_seats: StockLhbSeat[];
  announcements: StockAnnouncement[];
}
