export interface StockPool {
  id: number;
  pool_code: string;
  pool_name: string;
  pool_type: string;
  description: string | null;
  is_system: boolean;
  is_enabled: boolean;
  is_dynamic: boolean;
  dynamic_rule: string | null;
  sort_order: number;
  member_count: number;
  realtime_policy: StockPoolRealtimePolicy;
  created_at: string;
  updated_at: string;
}

export interface StockPoolRealtimePolicy {
  is_enabled: boolean;
  priority: number;
  quote_lane: 'hot' | 'warm' | 'off';
  minute_lane: 'guaranteed' | 'rotating' | 'off';
  updated_at: string | null;
}

export interface StockPoolMember {
  stock_code: string;
  stock_name: string | null;
  created_at: string;
}

export interface StockPoolMemberPage {
  items: StockPoolMember[];
  total: number;
  page: number;
  page_size: number;
}

export interface StockPoolCandidate {
  stock_code: string;
  stock_name: string;
  is_member: boolean;
}

export interface StockPoolMemberBatchResult {
  added_count: number;
  existing_codes: string[];
  stock_codes: string[];
}

export interface StockPoolSector {
  sector_code: string;
  sector_name: string;
  sector_type: 'concept' | 'industry' | string;
  source: string | null;
}

export interface StockPoolMemberDetail {
  pool_code: string;
  stock_code: string;
  stock_name: string;
  market: string;
  exchange: string | null;
  list_date: string | null;
  status: string;
  industry: string | null;
  area: string | null;
  concepts: StockPoolSector[];
  industries: StockPoolSector[];
}

export interface StockProfile {
  stock_code: string;
  stock_name: string;
  market: string;
  exchange: string | null;
  status: string;
  is_st: boolean;
  tushare_industry: string | null;
  eligible_for_emotion_and_strategy: boolean;
  concepts: StockPoolSector[];
  tushare_industries: StockPoolSector[];
  sw_industries: Array<{ universe_id: string; universe_name: string; taxonomy_level: 'sw1' | 'sw2' | 'sw3' | string; logical_group_key: string | null }>;
  stock_pools: Array<{
    pool_code: string;
    pool_name: string;
    pool_type: string;
    is_system: boolean;
    realtime_enabled: boolean | null;
    realtime_priority: number | null;
    quote_lane: 'hot' | 'warm' | 'off' | null;
    minute_lane: 'guaranteed' | 'rotating' | 'off' | null;
  }>;
}

export interface StockPoolCatalogItem {
  catalog_type: 'system' | 'strategy' | 'user' | 'topic' | 'industry' | string;
  item_code: string;
  item_name: string;
  member_count: number;
  source: string;
  updated_at: string | null;
  is_enabled: boolean;
  realtime_policy?: StockPoolRealtimePolicy;
  realtime?: {
    change_pct?: number | null;
    average_change_pct?: number | null;
    heat_score?: number | null;
    coverage_pct?: number | null;
  } | null;
}
