import { createRouter, createWebHistory } from 'vue-router';
import AdminLayout from '@/components/AdminLayout.vue';
import ConfigCenter from '@/views/ConfigCenter.vue';
import SchedulerCenter from '@/views/SchedulerCenter.vue';

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      component: AdminLayout,
      children: [
        { path: '', redirect: '/settings/search' },
        { path: 'settings/:domain?', name: 'settings-center', component: ConfigCenter },
        { path: 'scheduler', name: 'scheduler-center', component: SchedulerCenter },
        { path: 'config/:domain?', redirect: (to) => `/settings/${to.params.domain || 'search'}` },
      ],
    },
  ],
});

export default router;
