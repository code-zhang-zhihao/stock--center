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
  created_at: string;
  updated_at: string;
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
