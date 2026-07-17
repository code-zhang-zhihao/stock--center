import { requestData } from './client';
import type {
  BrowseSectorPage,
  BrowseSectorStocks,
  SectorAnalysisBar,
  SectorAnalysisOverview,
  SectorAnalysisSeries,
  SectorDashboardData,
  SectorLeaderPage,
  SectorMoneyFlowPoint,
  SectorProvider,
  SectorType,
  StockAnalysisEvents,
  StockAnalysisFactors,
  StockAnalysisMinuteSeries,
  StockAnalysisOverview,
  StockAnalysisRealtime,
  StockAnalysisSearchResult,
  StockAnalysisSeries,
  StockDailyBar,
  StockFundFlowSeries,
} from '@/types/market-data';

export const marketDataApi = {
  browseSectors: (params: {
    sectorType: SectorType;
    provider: SectorProvider;
    keyword?: string;
    page: number;
    pageSize: number;
  }) => requestData<BrowseSectorPage>({
    method: 'GET',
    url: '/market-data/browse/sectors',
    params: {
      sector_type: params.sectorType,
      provider: params.provider,
      keyword: params.keyword || undefined,
      page: params.page,
      page_size: params.pageSize,
    },
  }),
  browseSectorStocks: (sectorCode: string, params: {
    keyword?: string;
    status?: string;
    page: number;
    pageSize: number;
  }) => requestData<BrowseSectorStocks>({
    method: 'GET',
    url: `/market-data/browse/sectors/${encodeURIComponent(sectorCode)}/stocks`,
    params: {
      keyword: params.keyword || undefined,
      status: params.status || undefined,
      page: params.page,
      page_size: params.pageSize,
    },
  }),
  searchSectorAnalysis: (params: { keyword?: string; limit?: number }) => requestData<{ items: BrowseSectorPage['items']; total: number }>({
    method: 'GET',
    url: '/market-data/sector-analysis/search',
    params: {
      keyword: params.keyword || undefined,
      limit: params.limit || 20,
    },
  }),
  sectorOverview: (sectorCode: string) => requestData<SectorAnalysisOverview>({
    method: 'GET',
    url: `/market-data/sector-analysis/${encodeURIComponent(sectorCode)}/overview`,
  }),
  sectorBars: (sectorCode: string, params: { startDate?: string; endDate?: string; limit?: number }) => requestData<SectorAnalysisSeries<SectorAnalysisBar>>({
    method: 'GET',
    url: `/market-data/sector-analysis/${encodeURIComponent(sectorCode)}/bars`,
    params: {
      start_date: params.startDate || undefined,
      end_date: params.endDate || undefined,
      limit: params.limit || 120,
    },
  }),
  sectorMoneyFlow: (sectorCode: string, params: { startDate?: string; endDate?: string; limit?: number }) => requestData<SectorAnalysisSeries<SectorMoneyFlowPoint>>({
    method: 'GET',
    url: `/market-data/sector-analysis/${encodeURIComponent(sectorCode)}/money-flow`,
    params: {
      start_date: params.startDate || undefined,
      end_date: params.endDate || undefined,
      limit: params.limit || 120,
    },
  }),
  sectorLeaders: (sectorCode: string, params: { limit?: number } = {}) => requestData<SectorLeaderPage>({
    method: 'GET',
    url: `/market-data/sector-analysis/${encodeURIComponent(sectorCode)}/leaders`,
    params: {
      limit: params.limit || 30,
    },
  }),
  sectorAnalysisStocks: (sectorCode: string, params: {
    keyword?: string;
    status?: string;
    page: number;
    pageSize: number;
  }) => requestData<BrowseSectorStocks>({
    method: 'GET',
    url: `/market-data/sector-analysis/${encodeURIComponent(sectorCode)}/stocks`,
    params: {
      keyword: params.keyword || undefined,
      status: params.status || undefined,
      page: params.page,
      page_size: params.pageSize,
    },
  }),
  sectorDashboard: (params: { sectorType?: SectorType; limit?: number } = {}) => requestData<SectorDashboardData>({
    method: 'GET',
    url: '/market-data/sector-analysis/dashboard',
    params: {
      sector_type: params.sectorType || 'concept',
      limit: params.limit || 50,
    },
  }),
  stockAnalysisSearch: (params: { keyword?: string; limit?: number }) => requestData<StockAnalysisSearchResult>({
    method: 'GET',
    url: '/market-data/stock-analysis/search',
    params: {
      keyword: params.keyword || undefined,
      limit: params.limit || 20,
    },
  }),
  stockAnalysisOverview: (stockCode: string) => requestData<StockAnalysisOverview>({
    method: 'GET',
    url: `/market-data/stock-analysis/${encodeURIComponent(stockCode)}/overview`,
  }),
  stockAnalysisRealtime: (stockCode: string) => requestData<StockAnalysisRealtime>({
    method: 'GET',
    url: `/market-data/stock-analysis/${encodeURIComponent(stockCode)}/realtime`,
  }),
  stockAnalysisDailyBars: (stockCode: string, params: { limit?: number } = {}) => requestData<StockAnalysisSeries<StockDailyBar>>({
    method: 'GET',
    url: `/market-data/stock-analysis/${encodeURIComponent(stockCode)}/daily-bars`,
    params: {
      limit: params.limit || 250,
    },
  }),
  stockAnalysisMinuteBars: (stockCode: string, params: { tradeDate?: string; limit?: number } = {}) => requestData<StockAnalysisMinuteSeries>({
    method: 'GET',
    url: `/market-data/stock-analysis/${encodeURIComponent(stockCode)}/minute-bars`,
    params: {
      trade_date: params.tradeDate || undefined,
      limit: params.limit || 2000,
    },
  }),
  stockAnalysisFactors: (stockCode: string, params: { tradeDate?: string; lookback?: number } = {}) => requestData<StockAnalysisFactors>({
    method: 'GET',
    url: `/market-data/stock-analysis/${encodeURIComponent(stockCode)}/factors`,
    params: {
      trade_date: params.tradeDate || undefined,
      lookback: params.lookback || 60,
    },
  }),
  stockAnalysisFundFlow: (stockCode: string, params: { lookback?: number } = {}) => requestData<StockFundFlowSeries>({
    method: 'GET',
    url: `/market-data/stock-analysis/${encodeURIComponent(stockCode)}/fund-flow`,
    params: {
      lookback: params.lookback || 60,
    },
  }),
  stockAnalysisEvents: (stockCode: string, params: { lookback?: number } = {}) => requestData<StockAnalysisEvents>({
    method: 'GET',
    url: `/market-data/stock-analysis/${encodeURIComponent(stockCode)}/events`,
    params: {
      lookback: params.lookback || 60,
    },
  }),
};
