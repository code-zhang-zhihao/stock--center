import { requestData } from './client';
import type {
  StockPool,
  StockPoolCandidate,
  StockPoolCatalogItem,
  StockPoolMemberBatchResult,
  StockPoolMemberDetail,
  StockPoolMemberPage,
  StockProfile,
} from '@/types/stock-pool';

export const stockPoolApi = {
  list: () => requestData<StockPool[]>({ method: 'GET', url: '/stock-pools' }),
  catalog: (scope?: 'system' | 'strategy' | 'user' | 'topic' | 'industry') => requestData<StockPoolCatalogItem[]>({
    method: 'GET', url: '/stock-pools/catalog', params: { scope },
  }),
  create: (payload: { pool_code: string; pool_name: string; description?: string | null }) =>
    requestData<StockPool>({ method: 'POST', url: '/stock-pools', data: payload }),
  update: (poolCode: string, payload: { pool_name?: string; description?: string | null; is_enabled?: boolean }) =>
    requestData<StockPool>({ method: 'PATCH', url: `/stock-pools/${encodeURIComponent(poolCode)}`, data: payload }),
  remove: (poolCode: string) => requestData<StockPool>({ method: 'DELETE', url: `/stock-pools/${encodeURIComponent(poolCode)}` }),
  members: (poolCode: string, params: { keyword?: string; page: number; pageSize: number }) =>
    requestData<StockPoolMemberPage>({
      method: 'GET',
      url: `/stock-pools/${encodeURIComponent(poolCode)}/members`,
      params: { keyword: params.keyword || undefined, page: params.page, page_size: params.pageSize },
    }),
  candidateStocks: (poolCode: string, keyword: string) =>
    requestData<StockPoolCandidate[]>({
      method: 'GET',
      url: `/stock-pools/${encodeURIComponent(poolCode)}/candidate-stocks`,
      params: { keyword, limit: 20 },
    }),
  addMembers: (poolCode: string, stockCodes: string[]) =>
    requestData<StockPoolMemberBatchResult>({
      method: 'POST',
      url: `/stock-pools/${encodeURIComponent(poolCode)}/members/batch`,
      data: { stock_codes: stockCodes },
    }),
  removeMember: (poolCode: string, stockCode: string) =>
    requestData<{ pool_code: string; stock_code: string; deleted: boolean }>({
      method: 'DELETE',
      url: `/stock-pools/${encodeURIComponent(poolCode)}/members/${encodeURIComponent(stockCode)}`,
    }),
  memberDetail: (poolCode: string, stockCode: string) =>
    requestData<StockPoolMemberDetail>({
      method: 'GET',
      url: `/stock-pools/${encodeURIComponent(poolCode)}/members/${encodeURIComponent(stockCode)}/detail`,
    }),
  profile: (stockCode: string) => requestData<StockProfile>({
    method: 'GET',
    url: `/stock-pools/profiles/${encodeURIComponent(stockCode)}`,
  }),
};
