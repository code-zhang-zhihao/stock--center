<template>
  <main class="admin-shell">
    <aside class="admin-sidebar">
      <div class="brand-block">
        <div class="brand-mark">SC</div>
        <div>
          <div class="brand-title">stock-center</div>
          <div class="brand-subtitle">管理后台</div>
        </div>
      </div>

      <nav class="main-nav">
        <router-link
          v-for="item in navItems"
          :key="item.path"
          :to="item.path"
          class="main-nav-item"
          :class="{ active: isActive(item.matchPrefix) }"
        >
          <component :is="item.icon" :size="18" />
          <span>{{ item.label }}</span>
        </router-link>
      </nav>

      <div class="sidebar-note">
        <ShieldCheck :size="16" />
        <span>配置、任务和运行记录统一在本地后端管理。</span>
      </div>
    </aside>

    <section class="admin-content">
      <router-view />
    </section>
  </main>
</template>

<script setup lang="ts">
import { Activity, CalendarClock, Database, Gauge, Layers3, LineChart, ListChecks, Settings, ShieldCheck } from 'lucide-vue-next';
import { useRoute } from 'vue-router';

const route = useRoute();

const navItems = [
  { path: '/settings/search', matchPrefix: '/settings', label: '系统设置中心', icon: Settings },
  { path: '/data-center', matchPrefix: '/data-center', label: '数据中心', icon: Database },
  { path: '/market-overview', matchPrefix: '/market-overview', label: '实时市场总览', icon: Gauge },
  { path: '/scheduler', matchPrefix: '/scheduler', label: '调度任务', icon: CalendarClock },
  { path: '/sector-dashboard', matchPrefix: '/sector-dashboard', label: '板块资金大屏', icon: Activity },
  { path: '/sectors', matchPrefix: '/sectors', label: '板块中心', icon: Layers3 },
  { path: '/stock-pools', matchPrefix: '/stock-pools', label: '股票池', icon: ListChecks },
  { path: '/market', matchPrefix: '/market', label: '个股行情', icon: LineChart },
];

function isActive(prefix: string) {
  return route.path.startsWith(prefix);
}
</script>

<style scoped>
.admin-shell {
  width: 100%;
  min-width: 0;
  min-height: 100vh;
  display: grid;
  grid-template-columns: 240px minmax(0, 1fr);
}

.admin-sidebar {
  min-width: 0;
  overflow: hidden;
  background: #17212b;
  color: #f8fafc;
  padding: 18px 14px;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.brand-block {
  padding: 6px 8px 14px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
  display: flex;
  align-items: center;
  gap: 12px;
}

.brand-mark {
  width: 36px;
  height: 36px;
  border-radius: 6px;
  display: grid;
  place-items: center;
  background: #1f8a70;
  font-weight: 700;
}

.brand-title {
  font-weight: 700;
}

.brand-subtitle,
.sidebar-note {
  color: #a8b3bd;
  font-size: 12px;
}

.main-nav {
  display: grid;
  gap: 6px;
}

.main-nav-item {
  min-height: 42px;
  border-radius: 6px;
  padding: 0 10px;
  display: grid;
  grid-template-columns: 20px 1fr;
  align-items: center;
  gap: 8px;
  color: #d7dee4;
  text-decoration: none;
}

.main-nav-item:hover,
.main-nav-item.active {
  background: rgba(255, 255, 255, 0.1);
  color: #fff;
}

.sidebar-note {
  margin-top: auto;
  display: flex;
  gap: 8px;
  align-items: flex-start;
  line-height: 1.5;
}

.admin-content {
  min-width: 0;
  overflow-x: hidden;
}

@media (max-width: 860px) {
  .admin-shell {
    grid-template-columns: minmax(0, 1fr);
  }

  .admin-sidebar {
    position: static;
    gap: 10px;
    padding: 12px 14px;
  }

  .brand-block {
    padding: 2px 0 10px;
  }

  .main-nav {
    display: flex;
    gap: 6px;
    overflow-x: auto;
    padding-bottom: 2px;
    scrollbar-width: none;
  }

  .main-nav::-webkit-scrollbar {
    display: none;
  }

  .main-nav-item {
    min-width: max-content;
    min-height: 36px;
    grid-template-columns: 18px auto;
    padding: 0 9px;
    font-size: 13px;
  }

  .sidebar-note {
    display: none;
  }
}
</style>
