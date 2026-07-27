import { requestData } from './client';
import type {
  RealtimeMarketEvents,
  RealtimeMarketOverview,
  RealtimeMarketTimeline,
  PostCloseMarketStructure,
  RealtimePoolList,
  RealtimeRuntimeStatus,
  RealtimeSectorList,
} from '@/types/realtime-market';

export const realtimeMarketApi = {
  marketOverview: () => requestData<RealtimeMarketOverview>({ method: 'GET', url: '/realtime/market-overview' }),
  marketTimeline: (limit = 180) => requestData<RealtimeMarketTimeline>({ method: 'GET', url: '/realtime/market-timeline', params: { limit } }),
  marketEvents: (limit = 80) => requestData<RealtimeMarketEvents>({ method: 'GET', url: '/realtime/market-events', params: { limit } }),
  postCloseStructure: () => requestData<PostCloseMarketStructure>({ method: 'GET', url: '/realtime/post-close-structure' }),
  sectors: (sectorType: 'concept' | 'industry', limit = 100) => requestData<RealtimeSectorList>({
    method: 'GET',
    url: '/realtime/sectors',
    params: { sector_type: sectorType, limit },
  }),
  pools: (limit = 100) => requestData<RealtimePoolList>({ method: 'GET', url: '/realtime/pools', params: { limit } }),
  status: () => requestData<RealtimeRuntimeStatus>({ method: 'GET', url: '/realtime/status' }),
};
