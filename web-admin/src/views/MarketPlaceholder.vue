<template>
  <main class="workspace market-placeholder">
    <header class="topbar">
      <div>
        <h1>行情详情</h1>
        <p>股票 <span class="mono">{{ stockCode || '-' }}</span> 的行情详情页正在接入。</p>
      </div>
      <n-button secondary @click="router.back()">
        <template #icon><ArrowLeft :size="16" /></template>
        返回
      </n-button>
    </header>
    <section class="placeholder-surface">
      <n-empty description="行情、K 线和资金流将在后续行情详情页提供" />
    </section>
  </main>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { ArrowLeft } from 'lucide-vue-next';
import { NButton, NEmpty } from 'naive-ui';

const route = useRoute();
const router = useRouter();
const stockCode = computed(() => String(route.query.stock_code || ''));
</script>

<style scoped>
.market-placeholder { padding: 24px; }
.topbar { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; margin-bottom: 18px; }
.topbar h1 { margin: 0; font-size: 24px; }
.topbar p { margin: 6px 0 0; color: #667085; }
.placeholder-surface { min-height: 360px; display: grid; place-items: center; border: 1px solid #d8e0e5; background: #fff; }
@media (max-width: 900px) { .market-placeholder { padding: 14px; } }
</style>
