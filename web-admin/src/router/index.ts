import { createRouter, createWebHistory } from 'vue-router';
import AdminLayout from '@/components/AdminLayout.vue';
import ConfigCenter from '@/views/ConfigCenter.vue';
import DataCenter from '@/views/DataCenter.vue';
import EmotionModelCenter from '@/views/EmotionModelCenter.vue';
import PostCloseMarketReview from '@/views/PostCloseMarketReview.vue';
import RealtimeMarketOverview from '@/views/RealtimeMarketOverview.vue';
import SchedulerCenter from '@/views/SchedulerCenter.vue';
import SectorCenter from '@/views/SectorCenter.vue';
import SectorDashboard from '@/views/SectorDashboard.vue';
import SectorDetail from '@/views/SectorDetail.vue';
import StockPoolCenter from '@/views/StockPoolCenter.vue';
import StockMarketWorkbench from '@/views/StockMarketWorkbench.vue';

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      component: AdminLayout,
      children: [
        { path: '', redirect: '/settings/search' },
        { path: 'settings/:domain?', name: 'settings-center', component: ConfigCenter },
        { path: 'data-center', name: 'data-center', component: DataCenter },
        { path: 'market-overview', name: 'realtime-market-overview', component: RealtimeMarketOverview },
        { path: 'post-close-market', name: 'post-close-market-review', component: PostCloseMarketReview },
        { path: 'emotion-models', name: 'emotion-model-center', component: EmotionModelCenter },
        { path: 'scheduler', name: 'scheduler-center', component: SchedulerCenter },
        { path: 'sector-dashboard', name: 'sector-dashboard', component: SectorDashboard },
        { path: 'sectors', name: 'sector-center', component: SectorCenter },
        { path: 'sectors/:sectorCode', name: 'sector-detail', component: SectorDetail },
        { path: 'stock-pools', name: 'stock-pool-center', component: StockPoolCenter },
        { path: 'market', name: 'stock-market-workbench', component: StockMarketWorkbench },
        { path: 'config/:domain?', redirect: (to) => `/settings/${to.params.domain || 'search'}` },
      ],
    },
  ],
});

export default router;
