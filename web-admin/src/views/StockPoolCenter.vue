<template>
  <main class="workspace stock-pool-page">
    <header class="topbar">
      <div>
        <h1>股票池</h1>
        <p>管理系统池与自定义池；全市场范围由已同步的正常交易股票自动组成。</p>
      </div>
      <n-space>
        <n-button secondary :loading="loadingPools" @click="loadPools">
          <template #icon><RefreshCw :size="16" /></template>
        </n-button>
        <n-button type="primary" @click="openCreatePool">
          <template #icon><Plus :size="16" /></template>
          新建池
        </n-button>
      </n-space>
    </header>

    <div class="pool-workspace">
      <aside class="pool-list-panel">
        <div class="panel-heading">
          <span>股票池</span>
          <span class="muted">{{ pools.length }} 个</span>
        </div>
        <n-input v-model:value="poolKeyword" clearable size="small" placeholder="搜索池名称 / 编码" />
        <div class="pool-list-region">
          <n-spin :show="loadingPools" class="pool-list-spin">
            <n-empty v-if="filteredPools.length === 0" description="暂无股票池" />
            <button
              v-for="pool in filteredPools"
              :key="pool.pool_code"
              type="button"
              class="pool-row"
              :class="{ active: selectedPool?.pool_code === pool.pool_code }"
              @click="selectPool(pool.pool_code)"
            >
              <div class="pool-row-main">
                <strong>{{ pool.pool_name }}</strong>
                <span class="mono">{{ pool.pool_code }}</span>
              </div>
              <div class="pool-row-meta">
                <n-tag size="small" :bordered="false" :type="pool.is_enabled ? 'success' : 'warning'">
                  {{ pool.is_enabled ? '启用' : '停用' }}
                </n-tag>
                <strong>{{ pool.member_count }}</strong>
              </div>
            </button>
          </n-spin>
        </div>
      </aside>

      <section class="members-panel">
        <n-empty v-if="!selectedPool && !loadingPools" description="从左侧选择一个股票池" />
        <div v-else-if="selectedPool" class="members-content">
          <div class="pool-detail-head">
            <div class="pool-detail-main">
              <div class="title-line">
                <h2>{{ selectedPool.pool_name }}</h2>
                <n-tag size="small" :bordered="false" :type="selectedPool.is_enabled ? 'success' : 'warning'">
                  {{ selectedPool.is_enabled ? '启用' : '停用' }}
                </n-tag>
                <n-tag v-if="selectedPool.is_system" size="small" :bordered="false">系统预置</n-tag>
                <n-tag v-if="selectedPool.is_dynamic" size="small" :bordered="false" type="info">动态范围</n-tag>
              </div>
              <span class="mono muted">{{ selectedPool.pool_code }}</span>
              <p v-if="selectedPool.description">{{ selectedPool.description }}</p>
              <p v-else-if="selectedPool.is_dynamic">成员随 <span class="mono">t_stock.status=active</span> 自动变化，不保存实体成员关系。</p>
            </div>
            <div class="pool-detail-actions">
              <n-button secondary @click="openEditPool">
                <template #icon><Pencil :size="16" /></template>
                {{ selectedPool.is_system ? '配置' : '编辑' }}
              </n-button>
              <n-button v-if="!selectedPool.is_system" secondary type="error" @click="confirmDeletePool">
                <template #icon><Trash2 :size="16" /></template>
              </n-button>
            </div>
          </div>

          <section class="realtime-policy-panel">
            <div>
              <strong>实时监控</strong>
              <p>{{ realtimePolicySummary }}</p>
            </div>
            <n-tag :type="selectedPool.is_enabled && selectedPool.realtime_policy.is_enabled ? 'success' : 'default'" :bordered="false">
              {{ selectedPool.is_enabled && selectedPool.realtime_policy.is_enabled ? '已接入' : '未接入' }}
            </n-tag>
          </section>

          <div class="members-toolbar">
            <n-input v-model:value="memberKeyword" clearable size="small" placeholder="搜索股票代码 / 名称" @keyup.enter="searchMembers" />
            <n-button quaternary circle title="搜索成员" @click="searchMembers">
              <template #icon><Search :size="16" /></template>
            </n-button>
            <n-button v-if="!selectedPool.is_dynamic" type="primary" secondary @click="openBatchAdd">
              <template #icon><Plus :size="16" /></template>
              添加股票
            </n-button>
          </div>

          <n-spin class="member-table-region" :show="loadingMembers">
            <n-data-table :columns="memberColumns" :data="members.items" :pagination="false" :max-height="tableMaxHeight" size="small" striped :row-key="memberRowKey" />
          </n-spin>

          <div class="members-footer">
            <span class="page-hint">显示 {{ memberRangeLabel }} / {{ members.total }}，每页 {{ pageSize }} 条</span>
            <n-pagination
              v-if="members.total > pageSize"
              v-model:page="memberPage"
              :page-size="pageSize"
              :item-count="members.total"
              size="small"
              @update:page="loadMembers"
            />
          </div>
        </div>
      </section>
    </div>

    <section class="catalog-panel">
      <div class="catalog-heading">
        <div>
          <strong>题材、行业与池目录</strong>
          <p>题材使用 Tushare 概念，行业使用 TickFlow 申万层级；两者不等同于股票池。</p>
        </div>
        <n-space>
          <n-select v-model:value="catalogScope" size="small" :options="catalogScopeOptions" style="width: 150px" />
          <n-button secondary size="small" :loading="loadingCatalog" @click="loadCatalog">刷新目录</n-button>
        </n-space>
      </div>
      <n-data-table :columns="catalogColumns" :data="catalogItems" :loading="loadingCatalog" :pagination="{ pageSize: 12 }" size="small" />
    </section>

    <n-modal
      v-model:show="poolModalOpen"
      preset="card"
      :title="editingPool ? '编辑股票池' : '新建股票池'"
      :style="{ width: 'min(560px, calc(100vw - 32px))' }"
    >
      <n-form label-placement="top">
        <n-form-item label="池编码">
          <n-input v-model:value="poolForm.pool_code" class="mono" :disabled="Boolean(editingPool)" placeholder="例如: my_watchlist" />
        </n-form-item>
        <n-form-item v-if="!editingPool?.is_system" label="池名称">
          <n-input v-model:value="poolForm.pool_name" placeholder="例如: 新能源观察池" />
        </n-form-item>
        <n-form-item v-if="!editingPool?.is_system" label="说明">
          <n-input v-model:value="poolForm.description" type="textarea" :autosize="{ minRows: 3, maxRows: 6 }" />
        </n-form-item>
        <n-form-item v-if="editingPool?.is_system" label="系统预置池">
          <div class="system-pool-note">名称和编码由系统维护；你仍可配置启停和实时监控方式。</div>
        </n-form-item>
        <n-divider title-placement="left">运行设置</n-divider>
        <n-form-item label="股票池状态">
          <n-switch v-model:value="poolForm.is_enabled">
            <template #checked>启用</template>
            <template #unchecked>停用</template>
          </n-switch>
        </n-form-item>
        <n-form-item label="参与实时监控">
          <div class="form-control-with-help">
            <n-switch
              v-model:value="poolForm.realtime_policy.is_enabled"
              :disabled="isEditingDynamicUniverse"
              @update:value="applyRealtimeDefaults"
            >
              <template #checked>开启</template>
              <template #unchecked>关闭</template>
            </n-switch>
            <span>{{ isEditingDynamicUniverse ? '全市场范围只用于市场总览，不能作为实时监控目标。' : '开启后，池内股票将参与实时行情和分钟线刷新。' }}</span>
          </div>
        </n-form-item>
        <template v-if="poolForm.realtime_policy.is_enabled && !isEditingDynamicUniverse">
          <n-form-item label="监控优先级">
            <n-select v-model:value="poolForm.realtime_policy.priority" :options="realtimePriorityOptions" />
          </n-form-item>
          <n-form-item label="实时行情刷新">
            <n-select v-model:value="poolForm.realtime_policy.quote_lane" :options="quoteLaneOptions" />
          </n-form-item>
          <n-form-item label="分钟线刷新">
            <n-select v-model:value="poolForm.realtime_policy.minute_lane" :options="minuteLaneOptions" />
          </n-form-item>
        </template>
      </n-form>
      <template #footer>
        <n-space justify="end">
          <n-button @click="poolModalOpen = false">取消</n-button>
          <n-button type="primary" :loading="savingPool" @click="savePool">保存</n-button>
        </n-space>
      </template>
    </n-modal>

    <n-modal v-model:show="batchModalOpen" preset="card" title="添加股票" :style="{ width: 'min(620px, calc(100vw - 32px))' }">
      <div class="candidate-search-panel">
        <div class="candidate-search-input">
          <n-input
            v-model:value="candidateKeyword"
            clearable
            placeholder="搜索股票名称或代码"
            :loading="loadingCandidates"
            @keyup.enter="searchCandidates"
          >
            <template #prefix><Search :size="16" /></template>
          </n-input>
          <n-button quaternary circle title="搜索股票" :loading="loadingCandidates" @click="searchCandidates">
            <template #icon><Search :size="16" /></template>
          </n-button>
        </div>

        <div class="candidate-results">
          <n-spin :show="loadingCandidates">
            <n-empty v-if="!candidateKeyword.trim()" size="small" description="输入股票名称或代码后开始搜索" />
            <n-empty v-else-if="candidateResults.length === 0" size="small" description="未找到正常交易的股票" />
            <template v-else>
              <button
                v-for="candidate in candidateResults"
                :key="candidate.stock_code"
                type="button"
                class="candidate-row"
                :class="{ selected: isCandidateSelected(candidate.stock_code), disabled: candidate.is_member }"
                :disabled="candidate.is_member"
                @click="toggleCandidate(candidate)"
              >
                <span class="candidate-main">
                  <strong>{{ candidate.stock_name }}</strong>
                  <span class="mono">{{ candidate.stock_code }}</span>
                </span>
                <n-tag v-if="candidate.is_member" size="small" :bordered="false" type="default">已在池中</n-tag>
                <n-tag v-else-if="isCandidateSelected(candidate.stock_code)" size="small" :bordered="false" type="success">已选择</n-tag>
              </button>
            </template>
          </n-spin>
        </div>

        <section class="selected-candidates">
          <div class="selected-candidates-title">
            <strong>已选择</strong>
            <span class="page-hint">{{ selectedCandidates.length }} 只</span>
          </div>
          <n-empty v-if="selectedCandidates.length === 0" size="small" description="点击上方搜索结果添加" />
          <n-space v-else wrap>
            <n-tag
              v-for="candidate in selectedCandidates"
              :key="candidate.stock_code"
              closable
              type="success"
              @close="removeSelectedCandidate(candidate.stock_code)"
            >
              {{ candidate.stock_name }} {{ candidate.stock_code }}
            </n-tag>
          </n-space>
        </section>
      </div>
      <template #footer>
        <n-space justify="end">
          <n-button @click="closeBatchAdd">取消</n-button>
          <n-button type="primary" :disabled="selectedCandidates.length === 0" :loading="savingMembers" @click="saveSelectedMembers">添加</n-button>
        </n-space>
      </template>
    </n-modal>

    <n-modal v-model:show="detailModalOpen" preset="card" title="股票详情" :style="{ width: 'min(720px, calc(100vw - 32px))' }">
      <n-spin :show="loadingDetail">
        <template v-if="memberDetail">
          <div class="stock-summary-grid">
            <div><span>股票代码</span><strong class="mono">{{ memberDetail.stock_code }}</strong></div>
            <div><span>股票名称</span><strong>{{ memberDetail.stock_name }}</strong></div>
            <div><span>交易所</span><strong>{{ memberDetail.exchange || '-' }}</strong></div>
            <div><span>所属行业</span><strong>{{ memberDetail.industry || '-' }}</strong></div>
            <div><span>地区</span><strong>{{ memberDetail.area || '-' }}</strong></div>
            <div><span>上市日期</span><strong>{{ memberDetail.list_date || '-' }}</strong></div>
          </div>
          <section class="sector-section">
            <h3>概念</h3>
            <n-empty v-if="memberDetail.concepts.length === 0" size="small" description="暂无已同步概念" />
            <n-space v-else wrap>
              <n-tag v-for="sector in memberDetail.concepts" :key="sector.sector_code" size="small" type="success">{{ sector.sector_name }}</n-tag>
            </n-space>
          </section>
          <section class="sector-section">
            <h3>行业</h3>
            <n-empty v-if="memberDetail.industries.length === 0" size="small" description="暂无已同步行业" />
            <n-space v-else wrap>
              <n-tag v-for="sector in memberDetail.industries" :key="sector.sector_code" size="small">{{ sector.sector_name }}</n-tag>
            </n-space>
          </section>
        </template>
      </n-spin>
      <template #footer>
        <n-space justify="end">
          <n-button @click="detailModalOpen = false">关闭</n-button>
          <n-button secondary :disabled="!memberDetail" @click="openMarketPlaceholder">
            <template #icon><ExternalLink :size="16" /></template>
            查看行情
          </n-button>
        </n-space>
      </template>
    </n-modal>
  </main>
</template>

<script setup lang="ts">
import { computed, h, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { useRouter } from 'vue-router';
import { ExternalLink, Pencil, Plus, RefreshCw, Search, Trash2 } from 'lucide-vue-next';
import {
  NButton,
  NDataTable,
  NDivider,
  NEmpty,
  NForm,
  NFormItem,
  NInput,
  NModal,
  NPagination,
  NSelect,
  NSpace,
  NSpin,
  NSwitch,
  NTag,
  useDialog,
  useMessage,
  type DataTableColumns,
} from 'naive-ui';
import { stockPoolApi } from '@/api/stock-pool';
import type { StockPool, StockPoolCandidate, StockPoolCatalogItem, StockPoolMember, StockPoolMemberDetail, StockPoolMemberPage, StockPoolRealtimePolicy } from '@/types/stock-pool';
import { formatTime } from '@/utils/json';

const router = useRouter();
const message = useMessage();
const dialog = useDialog();
const pageSize = 20;
const loadingPools = ref(false);
const loadingMembers = ref(false);
const loadingDetail = ref(false);
const savingPool = ref(false);
const savingMembers = ref(false);
const poolKeyword = ref('');
const memberKeyword = ref('');
const pools = ref<StockPool[]>([]);
const selectedPoolCode = ref('');
const memberPage = ref(1);
const members = ref<StockPoolMemberPage>({ items: [], total: 0, page: 1, page_size: pageSize });
const poolModalOpen = ref(false);
const batchModalOpen = ref(false);
const detailModalOpen = ref(false);
const editingPool = ref<StockPool | null>(null);
type RealtimePolicyForm = Omit<StockPoolRealtimePolicy, 'updated_at'>;
type PoolForm = {
  pool_code: string;
  pool_name: string;
  description: string;
  is_enabled: boolean;
  realtime_policy: RealtimePolicyForm;
};
const defaultRealtimePolicy = (): RealtimePolicyForm => ({
  is_enabled: false,
  priority: 20,
  quote_lane: 'hot',
  minute_lane: 'rotating',
});
const defaultPoolForm = (): PoolForm => ({
  pool_code: '',
  pool_name: '',
  description: '',
  is_enabled: true,
  realtime_policy: defaultRealtimePolicy(),
});
const poolForm = ref<PoolForm>(defaultPoolForm());
const candidateKeyword = ref('');
const candidateResults = ref<StockPoolCandidate[]>([]);
const selectedCandidates = ref<StockPoolCandidate[]>([]);
const loadingCandidates = ref(false);
const memberDetail = ref<StockPoolMemberDetail | null>(null);
const catalogScope = ref<'system' | 'strategy' | 'user' | 'topic' | 'industry'>('system');
const catalogItems = ref<StockPoolCatalogItem[]>([]);
const loadingCatalog = ref(false);
const tableMaxHeight = ref(440);
let candidateSearchTimer: ReturnType<typeof setTimeout> | undefined;

const selectedPool = computed(() => pools.value.find((pool) => pool.pool_code === selectedPoolCode.value) || null);
const isDynamicUniverse = computed(() => selectedPool.value?.is_dynamic && selectedPool.value.dynamic_rule === 'active_a_share');
const isEditingDynamicUniverse = computed(() => editingPool.value?.is_dynamic && editingPool.value.dynamic_rule === 'active_a_share');
const realtimePolicySummary = computed(() => {
  const pool = selectedPool.value;
  if (!pool) return '';
  if (!pool.is_enabled) return '股票池已停用，不参与实时资源分配。';
  if (isDynamicUniverse.value) return '全市场范围仅用于市场总览，不会占用候选行情或分钟线资源。';
  const policy = pool.realtime_policy;
  if (!policy.is_enabled) return '未接入实时监控；编辑股票池后可开启。';
  return `${priorityLabel(policy.priority)}｜${quoteLaneLabel(policy.quote_lane)}｜${minuteLaneLabel(policy.minute_lane)}`;
});
const filteredPools = computed(() => {
  const keyword = poolKeyword.value.trim().toLowerCase();
  if (!keyword) return pools.value;
  return pools.value.filter((pool) => [pool.pool_name, pool.pool_code].some((value) => value.toLowerCase().includes(keyword)));
});
const memberRangeLabel = computed(() => {
  if (members.value.total === 0) return '0';
  const start = (members.value.page - 1) * members.value.page_size + 1;
  return `${start}-${Math.min(start + members.value.items.length - 1, members.value.total)}`;
});

const memberColumns = computed<DataTableColumns<StockPoolMember>>(() => [
  { title: '代码', key: 'stock_code', width: 120, render: (row) => h('span', { class: 'mono' }, row.stock_code) },
  { title: '名称', key: 'stock_name', minWidth: 160, render: (row) => row.stock_name || '待基础资料同步' },
  { title: '加入时间', key: 'created_at', width: 180, render: (row) => formatTime(row.created_at) },
  {
    title: '操作', key: 'actions', width: selectedPool.value?.is_dynamic ? 80 : 150,
    render: (row) => h(NSpace, { size: 4 }, {
      default: () => [
        h(NButton, { size: 'tiny', secondary: true, onClick: () => openMemberDetail(row.stock_code) }, { default: () => '详情' }),
        ...(selectedPool.value?.is_dynamic
          ? []
          : [h(NButton, { size: 'tiny', tertiary: true, type: 'error', onClick: () => confirmRemoveMember(row.stock_code) }, { default: () => '移除' })]),
      ],
    }),
  },
]);
const catalogScopeOptions = [
  { label: '系统股票池', value: 'system' },
  { label: '策略股票池', value: 'strategy' },
  { label: '用户股票池', value: 'user' },
  { label: '题材', value: 'topic' },
  { label: '申万行业', value: 'industry' },
];
const quoteLaneOptions = [
  { label: '高频（每 10 秒刷新）', value: 'hot' },
  { label: '低频（每 60 秒刷新）', value: 'warm' },
  { label: '不拉取实时行情', value: 'off' },
];
const minuteLaneOptions = [
  { label: '保障（每分钟优先刷新）', value: 'guaranteed' },
  { label: '轮流刷新（覆盖更多股票）', value: 'rotating' },
  { label: '不拉取分钟线', value: 'off' },
];
const standardRealtimePriorityOptions = [
  { label: '最高（持仓）', value: 0 },
  { label: '高（重点关注）', value: 10 },
  { label: '常规（候选股票）', value: 20 },
  { label: '策略（策略池）', value: 30 },
  { label: '低（温观察）', value: 100 },
];
const realtimePriorityOptions = computed(() => {
  const priority = poolForm.value.realtime_policy.priority;
  return standardRealtimePriorityOptions.some((item) => item.value === priority)
    ? standardRealtimePriorityOptions
    : [...standardRealtimePriorityOptions, { label: `自定义（${priority}）`, value: priority }];
});
const catalogColumns = computed<DataTableColumns<StockPoolCatalogItem>>(() => [
  { title: '类别', key: 'catalog_type', width: 100, render: (row) => ({ system: '系统池', strategy: '策略池', user: '用户池', topic: '题材', industry: '行业' }[row.catalog_type] || row.catalog_type) },
  { title: '名称', key: 'item_name', minWidth: 180 },
  { title: '成员数', key: 'member_count', width: 90 },
  { title: '实时涨跌', key: 'realtime_change', width: 110, render: (row) => formatRealtimeChange(row) },
  { title: '热度 / 覆盖', key: 'realtime_heat', width: 120, render: (row) => row.realtime?.heat_score == null ? '-' : `${row.realtime.heat_score} / ${row.realtime.coverage_pct ?? '-'}%` },
  { title: '来源', key: 'source', width: 130, render: (row) => h('span', { class: 'mono' }, row.source) },
  { title: '更新时间', key: 'updated_at', width: 170, render: (row) => formatTime(row.updated_at) },
]);

function memberRowKey(row: StockPoolMember) {
  return row.stock_code;
}

function updateTableHeight() {
  tableMaxHeight.value = Math.max(300, Math.min(720, window.innerHeight - 330));
}

async function loadPools() {
  loadingPools.value = true;
  try {
    pools.value = await stockPoolApi.list();
    const nextCode = pools.value.some((pool) => pool.pool_code === selectedPoolCode.value)
      ? selectedPoolCode.value
      : pools.value[0]?.pool_code || '';
    if (nextCode !== selectedPoolCode.value) selectedPoolCode.value = nextCode;
    if (nextCode) await loadMembers();
  } catch (error) {
    message.error(errorMessage(error, '加载股票池失败'));
  } finally {
    loadingPools.value = false;
  }
}

async function loadCatalog() {
  loadingCatalog.value = true;
  try {
    catalogItems.value = await stockPoolApi.catalog(catalogScope.value);
  } catch (error) {
    message.error(errorMessage(error, '加载题材、行业与池目录失败'));
  } finally {
    loadingCatalog.value = false;
  }
}

function formatRealtimeChange(row: StockPoolCatalogItem) {
  const value = row.realtime?.change_pct ?? row.realtime?.average_change_pct;
  return value == null ? '-' : `${value >= 0 ? '+' : ''}${value.toFixed(2)}%`;
}

function priorityLabel(priority: number) {
  return ({ 0: '最高优先级', 10: '高优先级', 20: '常规优先级', 30: '策略优先级', 100: '低优先级' } as Record<number, string>)[priority]
    || `自定义优先级（${priority}）`;
}

function quoteLaneLabel(lane: RealtimePolicyForm['quote_lane']) {
  return ({ hot: '行情每 10 秒刷新', warm: '行情每 60 秒刷新', off: '不拉取实时行情' } as Record<RealtimePolicyForm['quote_lane'], string>)[lane];
}

function minuteLaneLabel(lane: RealtimePolicyForm['minute_lane']) {
  return ({ guaranteed: '分钟线每分钟保障', rotating: '分钟线轮流刷新', off: '不拉取分钟线' } as Record<RealtimePolicyForm['minute_lane'], string>)[lane];
}

async function loadMembers() {
  if (!selectedPoolCode.value) return;
  loadingMembers.value = true;
  try {
    members.value = await stockPoolApi.members(selectedPoolCode.value, {
      keyword: memberKeyword.value.trim(),
      page: memberPage.value,
      pageSize,
    });
  } catch (error) {
    message.error(errorMessage(error, '加载池成员失败'));
  } finally {
    loadingMembers.value = false;
  }
}

function selectPool(poolCode: string) {
  if (poolCode === selectedPoolCode.value) return;
  selectedPoolCode.value = poolCode;
  memberPage.value = 1;
  void loadMembers();
}

function searchMembers() {
  memberPage.value = 1;
  void loadMembers();
}

function openCreatePool() {
  editingPool.value = null;
  poolForm.value = defaultPoolForm();
  poolModalOpen.value = true;
}

function openEditPool() {
  if (!selectedPool.value) return;
  editingPool.value = selectedPool.value;
  const policy = selectedPool.value.realtime_policy;
  poolForm.value = {
    pool_code: selectedPool.value.pool_code,
    pool_name: selectedPool.value.pool_name,
    description: selectedPool.value.description || '',
    is_enabled: selectedPool.value.is_enabled,
    realtime_policy: {
      is_enabled: selectedPool.value.is_dynamic ? false : policy.is_enabled,
      priority: policy.priority,
      quote_lane: policy.quote_lane,
      minute_lane: policy.minute_lane,
    },
  };
  poolModalOpen.value = true;
}

function applyRealtimeDefaults(isEnabled: boolean) {
  if (!isEnabled) return;
  const policy = poolForm.value.realtime_policy;
  if (policy.priority === 1000) policy.priority = 20;
  if (policy.quote_lane === 'off') policy.quote_lane = 'hot';
  if (policy.minute_lane === 'off') policy.minute_lane = 'rotating';
}

async function savePool() {
  const payload = {
    pool_code: poolForm.value.pool_code.trim(),
    pool_name: poolForm.value.pool_name.trim(),
    description: poolForm.value.description.trim() || null,
    is_enabled: poolForm.value.is_enabled,
    realtime_policy: { ...poolForm.value.realtime_policy },
  };
  if (!payload.pool_code || !payload.pool_name) {
    message.warning('请填写池编码和池名称');
    return;
  }
  savingPool.value = true;
  try {
    const saved = editingPool.value
      ? await stockPoolApi.update(editingPool.value.pool_code, editingPool.value.is_system
        ? { is_enabled: payload.is_enabled, realtime_policy: payload.realtime_policy }
        : {
            pool_name: payload.pool_name,
            description: payload.description,
            is_enabled: payload.is_enabled,
            realtime_policy: payload.realtime_policy,
          })
      : await stockPoolApi.create(payload);
    selectedPoolCode.value = saved.pool_code;
    poolModalOpen.value = false;
    await loadPools();
    message.success(editingPool.value ? '股票池已更新' : '股票池已创建');
  } catch (error) {
    message.error(errorMessage(error, '保存股票池失败'));
  } finally {
    savingPool.value = false;
  }
}

function confirmDeletePool() {
  if (!selectedPool.value || selectedPool.value.is_system) return;
  const pool = selectedPool.value;
  dialog.error({
    title: '删除股票池',
    content: `将删除 ${pool.pool_name} 及其中全部成员关系，此操作不可恢复。`,
    positiveText: '删除',
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        await stockPoolApi.remove(pool.pool_code);
        selectedPoolCode.value = '';
        await loadPools();
        message.success('股票池已删除');
      } catch (error) {
        message.error(errorMessage(error, '删除股票池失败'));
      }
    },
  });
}

function openBatchAdd() {
  candidateKeyword.value = '';
  candidateResults.value = [];
  selectedCandidates.value = [];
  batchModalOpen.value = true;
}

function closeBatchAdd() {
  batchModalOpen.value = false;
  candidateKeyword.value = '';
  candidateResults.value = [];
  selectedCandidates.value = [];
}

async function searchCandidates() {
  if (!selectedPool.value) return;
  const keyword = candidateKeyword.value.trim();
  if (!keyword) {
    candidateResults.value = [];
    return;
  }
  loadingCandidates.value = true;
  try {
    const results = await stockPoolApi.candidateStocks(selectedPool.value.pool_code, keyword);
    if (candidateKeyword.value.trim() === keyword) candidateResults.value = results;
  } catch (error) {
    message.error(errorMessage(error, '搜索股票失败'));
  } finally {
    loadingCandidates.value = false;
  }
}

function isCandidateSelected(stockCode: string) {
  return selectedCandidates.value.some((candidate) => candidate.stock_code === stockCode);
}

function toggleCandidate(candidate: StockPoolCandidate) {
  if (candidate.is_member) return;
  if (isCandidateSelected(candidate.stock_code)) {
    removeSelectedCandidate(candidate.stock_code);
    return;
  }
  selectedCandidates.value = [...selectedCandidates.value, candidate];
}

function removeSelectedCandidate(stockCode: string) {
  selectedCandidates.value = selectedCandidates.value.filter((candidate) => candidate.stock_code !== stockCode);
}

async function saveSelectedMembers() {
  if (!selectedPool.value || selectedCandidates.value.length === 0) {
    message.warning('请先选择至少一只股票');
    return;
  }
  savingMembers.value = true;
  try {
    const result = await stockPoolApi.addMembers(selectedPool.value.pool_code, selectedCandidates.value.map((candidate) => candidate.stock_code));
    closeBatchAdd();
    memberPage.value = 1;
    await Promise.all([loadPools(), loadMembers()]);
    message.success(result.added_count ? `已添加 ${result.added_count} 只股票` : '股票已在当前池中');
  } catch (error) {
    message.error(errorMessage(error, '添加股票失败'));
  } finally {
    savingMembers.value = false;
  }
}

function confirmRemoveMember(stockCode: string) {
  if (!selectedPool.value) return;
  dialog.warning({
    title: '移除股票',
    content: `将从 ${selectedPool.value.pool_name} 移除 ${stockCode}。`,
    positiveText: '移除',
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        await stockPoolApi.removeMember(selectedPool.value!.pool_code, stockCode);
        await Promise.all([loadPools(), loadMembers()]);
        message.success('股票已移除');
      } catch (error) {
        message.error(errorMessage(error, '移除股票失败'));
      }
    },
  });
}

async function openMemberDetail(stockCode: string) {
  if (!selectedPool.value) return;
  detailModalOpen.value = true;
  loadingDetail.value = true;
  memberDetail.value = null;
  try {
    memberDetail.value = await stockPoolApi.memberDetail(selectedPool.value.pool_code, stockCode);
  } catch (error) {
    message.error(errorMessage(error, '加载股票详情失败'));
  } finally {
    loadingDetail.value = false;
  }
}

function openMarketPlaceholder() {
  if (!memberDetail.value) return;
  detailModalOpen.value = false;
  void router.push({ path: '/market', query: { stock_code: memberDetail.value.stock_code } });
}

function errorMessage(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback;
}

watch(memberKeyword, () => {
  memberPage.value = 1;
});

watch(candidateKeyword, () => {
  if (candidateSearchTimer) clearTimeout(candidateSearchTimer);
  if (!candidateKeyword.value.trim()) {
    candidateResults.value = [];
    return;
  }
  candidateSearchTimer = setTimeout(() => void searchCandidates(), 250);
});

watch(catalogScope, () => {
  void loadCatalog();
});

onMounted(() => {
  updateTableHeight();
  window.addEventListener('resize', updateTableHeight);
  void loadPools();
  void loadCatalog();
});
onBeforeUnmount(() => {
  window.removeEventListener('resize', updateTableHeight);
  if (candidateSearchTimer) clearTimeout(candidateSearchTimer);
});
</script>

<style scoped>
.stock-pool-page { padding: 22px 24px 24px; }
.topbar { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; margin-bottom: 16px; }
.topbar h1 { margin: 0; font-size: 24px; }
.topbar p { margin: 6px 0 0; color: #667085; }
.pool-workspace { height: max(560px, calc(100vh - 148px)); display: grid; grid-template-columns: minmax(288px, 320px) minmax(0, 1fr); overflow: hidden; border: 1px solid #d8e0e5; background: #fff; }
.catalog-panel { margin-top: 16px; border: 1px solid #d8e0e5; background: #fff; padding: 14px; }
.catalog-heading { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; margin-bottom: 12px; }
.catalog-heading strong { color: #344054; }
.catalog-heading p { margin: 4px 0 0; color: #667085; font-size: 12px; }
.pool-list-panel, .members-panel { height: 100%; min-width: 0; padding: 16px; box-sizing: border-box; }
.pool-list-panel { min-height: 0; display: flex; flex-direction: column; gap: 10px; border-right: 1px solid #d8e0e5; }
.panel-heading { display: flex; justify-content: space-between; color: #344054; font-size: 13px; font-weight: 700; }
.pool-list-region { min-height: 0; flex: 1; overflow-x: hidden; overflow-y: scroll; overscroll-behavior: contain; scrollbar-gutter: stable; }
.pool-list-spin, .pool-list-spin :deep(.n-spin-container) { height: auto; min-height: 100%; }
.pool-row { width: 100%; min-height: 62px; padding: 9px 6px; display: flex; align-items: center; justify-content: space-between; gap: 10px; border: 0; border-bottom: 1px solid #edf1f3; background: transparent; color: #1f2933; text-align: left; cursor: pointer; }
.pool-row:hover, .pool-row.active { background: #e8f5f0; }
.pool-row.active { box-shadow: inset 3px 0 0 #1f8a70; }
.pool-row-main { min-width: 0; display: grid; gap: 4px; }
.pool-row-main strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pool-row-main span { overflow: hidden; color: #667085; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.pool-row-meta { display: grid; justify-items: end; gap: 4px; color: #667085; font-size: 12px; }
.members-panel { min-height: 0; overflow: hidden; }
.members-content { height: 100%; min-height: 0; display: flex; flex-direction: column; gap: 12px; }
.pool-detail-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; padding: 2px 0 12px; border-bottom: 1px solid #d8e0e5; }
.pool-detail-main { min-width: 0; }
.title-line { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.title-line h2 { margin: 0; font-size: 20px; }
.pool-detail-main p { margin: 6px 0 0; color: #667085; font-size: 13px; }
.pool-detail-actions { display: flex; align-items: center; gap: 8px; }
.realtime-policy-panel { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 10px 12px; border: 1px solid #d8e0e5; background: #f8fafc; }
.realtime-policy-panel strong { color: #344054; font-size: 13px; }
.realtime-policy-panel p { margin: 4px 0 0; color: #667085; font-size: 12px; }
.system-pool-note, .form-control-with-help { color: #667085; font-size: 13px; line-height: 1.55; }
.form-control-with-help { display: flex; align-items: center; gap: 10px; }
.members-toolbar { display: flex; align-items: center; gap: 8px; padding: 8px; border: 1px solid #e4e7ec; background: #f8fafc; }
.members-toolbar :deep(.n-input) { min-width: 0; flex: 1; }
.member-table-region { min-height: 0; flex: 1; overflow: hidden; border: 1px solid #d8e0e5; }
.member-table-region :deep(.n-spin-container) { height: 100%; min-height: 0; overflow: auto; }
.members-footer { min-height: 34px; display: flex; justify-content: space-between; align-items: center; gap: 12px; }
.page-hint { color: #98a2b3; font-size: 12px; }
.candidate-search-panel { display: grid; gap: 14px; }
.candidate-search-input { display: flex; align-items: center; gap: 8px; }
.candidate-search-input :deep(.n-input) { flex: 1; }
.candidate-results { min-height: 230px; max-height: 300px; overflow-y: auto; border: 1px solid #e4e7ec; }
.candidate-results :deep(.n-spin-container) { min-height: 228px; }
.candidate-row { width: 100%; min-height: 50px; display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 8px 12px; border: 0; border-bottom: 1px solid #edf1f3; background: #fff; color: #1f2933; text-align: left; cursor: pointer; }
.candidate-row:last-child { border-bottom: 0; }
.candidate-row:hover, .candidate-row.selected { background: #e8f5f0; }
.candidate-row.selected { box-shadow: inset 3px 0 0 #1f8a70; }
.candidate-row.disabled { cursor: not-allowed; opacity: 0.64; }
.candidate-main { display: grid; gap: 3px; min-width: 0; }
.candidate-main strong, .candidate-main span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.candidate-main span { color: #667085; font-size: 12px; }
.selected-candidates { min-height: 92px; padding: 12px; border: 1px solid #e4e7ec; background: #f8fafc; }
.selected-candidates-title { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; font-size: 13px; }
.stock-summary-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); border: 1px solid #e4e7ec; }
.stock-summary-grid div { min-width: 0; padding: 10px 12px; border-right: 1px solid #e4e7ec; border-bottom: 1px solid #e4e7ec; }
.stock-summary-grid div:nth-child(2n) { border-right: 0; }
.stock-summary-grid div:nth-last-child(-n + 2) { border-bottom: 0; }
.stock-summary-grid span, .stock-summary-grid strong { display: block; }
.stock-summary-grid span { margin-bottom: 4px; color: #667085; font-size: 12px; }
.stock-summary-grid strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 14px; }
.sector-section { margin-top: 18px; }
.sector-section h3 { margin: 0 0 8px; font-size: 14px; }
@media (max-width: 900px) {
  .stock-pool-page { padding: 14px; }
  .topbar { align-items: center; }
  .topbar h1 { font-size: 22px; }
  .topbar p { max-width: 260px; font-size: 13px; line-height: 1.5; }
  .pool-workspace { height: auto; min-height: 0; grid-template-columns: 1fr; overflow: visible; }
  .catalog-heading { align-items: stretch; flex-direction: column; }
  .pool-list-panel { height: 314px; border-right: 0; border-bottom: 1px solid #d8e0e5; }
  .members-panel { min-height: 580px; }
  .members-content { height: 580px; }
  .members-footer { align-items: flex-start; flex-direction: column; }
}

@media (max-width: 560px) {
  .stock-pool-page { padding: 12px; }
  .topbar { align-items: flex-start; }
  .topbar > :last-child { flex-shrink: 0; }
  .topbar :deep(.n-button) { padding-inline: 10px; }
  .pool-list-panel, .members-panel { padding: 12px; }
  .pool-list-panel { height: 300px; }
  .pool-detail-head { gap: 10px; }
  .title-line h2 { font-size: 18px; }
  .pool-detail-main p { font-size: 12px; }
  .members-toolbar { flex-wrap: wrap; }
  .realtime-policy-panel { align-items: stretch; flex-direction: column; }
  .form-control-with-help { align-items: flex-start; flex-direction: column; gap: 6px; }
  .members-toolbar :deep(.n-input) { flex-basis: calc(100% - 42px); }
  .members-toolbar > :last-child { margin-left: auto; }
  .member-table-region :deep(.n-data-table-table) { min-width: 560px; }
  .members-footer { gap: 8px; }
  .stock-summary-grid { grid-template-columns: 1fr; }
  .stock-summary-grid div, .stock-summary-grid div:nth-child(2n) { border-right: 0; }
  .stock-summary-grid div:nth-last-child(-n + 2) { border-bottom: 1px solid #e4e7ec; }
  .stock-summary-grid div:last-child { border-bottom: 0; }
}
</style>
