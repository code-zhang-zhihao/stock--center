<template>
  <div class="market-chart" :style="{ height }">
    <n-spin :show="loading" class="chart-spin">
      <div v-if="empty" class="chart-empty">
        <n-empty :description="emptyText" />
      </div>
      <div v-else ref="chartEl" class="chart-canvas" />
    </n-spin>
  </div>
</template>

<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import * as echarts from 'echarts';
import type { ECharts, EChartsOption } from 'echarts';
import { NEmpty, NSpin } from 'naive-ui';

const props = withDefaults(defineProps<{
  option: EChartsOption;
  loading?: boolean;
  empty?: boolean;
  emptyText?: string;
  height?: string;
}>(), {
  loading: false,
  empty: false,
  emptyText: '暂无图表数据',
  height: '320px',
});

const chartEl = ref<HTMLDivElement | null>(null);
let chart: ECharts | null = null;
let observer: ResizeObserver | null = null;

function renderChart() {
  if (!chartEl.value || props.empty) return;
  if (!chart) {
    chart = echarts.init(chartEl.value);
  }
  chart.setOption(props.option, true);
}

watch(
  () => [props.option, props.empty],
  async () => {
    await nextTick();
    if (props.empty) {
      chart?.dispose();
      chart = null;
      return;
    }
    renderChart();
  },
  { deep: true },
);

onMounted(async () => {
  await nextTick();
  renderChart();
  if (chartEl.value) {
    observer = new ResizeObserver(() => chart?.resize());
    observer.observe(chartEl.value);
  }
});

onBeforeUnmount(() => {
  observer?.disconnect();
  chart?.dispose();
  chart = null;
});
</script>

<style scoped>
.market-chart {
  width: 100%;
  min-width: 0;
}

.chart-spin {
  width: 100%;
  height: 100%;
}

.chart-spin :deep(.n-spin-container),
.chart-spin :deep(.n-spin-content) {
  width: 100%;
  height: 100%;
}

.chart-canvas,
.chart-empty {
  width: 100%;
  height: 100%;
  min-height: 0;
}

.chart-empty {
  display: grid;
  place-items: center;
  border: 1px solid #d8e0e5;
  background: #fff;
}
</style>
