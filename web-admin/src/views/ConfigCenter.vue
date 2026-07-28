<template>
  <main class="workspace config-page">
      <header class="topbar">
        <div>
          <h1>系统设置中心</h1>
          <p>{{ activeCategoryMeta.description }}</p>
        </div>
        <n-button secondary :loading="loading" @click="reloadActive">
          <template #icon><RefreshCw :size="16" /></template>
        </n-button>
      </header>

      <nav class="category-strip">
        <button
          v-for="category in categories"
          :key="category.value"
          type="button"
          class="category-item"
          :class="{ active: activeCategory === category.value }"
          @click="switchCategory(category.value)"
        >
          <component :is="category.icon" :size="18" />
          <span>{{ category.label }}</span>
          <n-badge :value="categoryCounts[category.value]" :max="99" />
        </button>
      </nav>

      <div class="content-grid">
        <section class="object-panel">
          <div class="panel-title">
            <span>配置对象</span>
            <n-tag size="small" :bordered="false">{{ activeCategory }}</n-tag>
          </div>
          <n-input v-model:value="keyword" clearable size="small" placeholder="筛选名称 / code" />
          <n-spin :show="loading">
            <n-empty v-if="filteredItems.length === 0" description="暂无配置对象" />
            <div v-else class="object-list">
              <button
                v-for="item in filteredItems"
                :key="item.config.id"
                type="button"
                class="object-item"
                :class="{ active: selectedItem?.config.id === item.config.id }"
                @click="selectItem(item.config.id)"
              >
                <div class="object-main">
                  <span>{{ item.config.config_name }}</span>
                  <code>{{ item.config.config_code }}</code>
                </div>
                <div class="object-meta">
                  <n-tag size="small" :type="item.config.is_enabled ? 'success' : 'warning'" :bordered="false">
                    {{ item.config.is_enabled ? 'enabled' : 'disabled' }}
                  </n-tag>
                  <n-tag v-if="item.config.is_default" size="small" type="info" :bordered="false">default</n-tag>
                </div>
              </button>
            </div>
          </n-spin>
        </section>

        <section class="detail-panel">
          <n-empty v-if="!selectedItem" description="请选择一个配置对象" />
          <template v-else>
            <div class="detail-head">
              <div>
                <div class="title-row">
                  <h2>{{ selectedItem.config.config_name }}</h2>
                  <n-tag size="small" :type="selectedItem.config.is_enabled ? 'success' : 'warning'">
                    {{ selectedItem.config.is_enabled ? 'enabled' : 'disabled' }}
                  </n-tag>
                  <n-tag v-if="selectedItem.config.is_default" size="small" type="info">default</n-tag>
                </div>
                <div class="mono muted">{{ selectedItem.config.category_code }} / {{ selectedItem.config.config_code }}</div>
              </div>
            </div>

            <div class="metric-row">
              <div class="metric">
                <span>{{ activeCategory === 'search' ? '用途' : '参数' }}</span>
                <strong>{{ activeCategory === 'search' ? runtimePurposeLabel : selectedItem.options.length }}</strong>
              </div>
              <div class="metric">
                <span>{{ activeCategory === 'notification' ? '启用状态' : 'Active Values' }}</span>
                <strong>{{ activeCategory === 'notification' ? (selectedItem.config.is_enabled ? 'enabled' : 'disabled') : selectedItem.available_value_count }}</strong>
              </div>
              <div class="metric">
                <span>{{ activeCategory === 'notification' ? '默认' : '全部敏感值' }}</span>
                <strong>{{ activeCategory === 'notification' ? (selectedItem.config.is_default ? 'yes' : 'no') : selectedItem.values.length }}</strong>
              </div>
            </div>

            <n-tabs v-model:value="activeTab" type="segment" animated>
              <n-tab-pane name="basic" tab="基本信息">
                <n-form label-placement="top" class="basic-form">
                  <n-form-item label="展示名称">
                    <n-input v-model:value="configForm.config_name" />
                  </n-form-item>
                  <n-form-item label="启用">
                    <n-switch v-model:value="configForm.is_enabled" />
                  </n-form-item>
                  <n-form-item v-if="activeCategory !== 'search'" label="设为默认">
                    <n-switch v-model:value="configForm.is_default" />
                  </n-form-item>
                  <n-form-item label="描述" class="span-2">
                    <n-input v-model:value="configForm.description" type="textarea" :autosize="{ minRows: 2, maxRows: 5 }" />
                  </n-form-item>
                </n-form>
                <div class="actions-row">
                  <n-button type="primary" :loading="savingConfig" @click="saveConfig">保存基本信息</n-button>
                </div>
              </n-tab-pane>

              <n-tab-pane v-if="showOptionsTab" name="options" :tab="optionsTabLabel">
                <div class="helper-line">{{ optionHelperText }}</div>
                <n-empty v-if="optionRows.length === 0" description="暂无可编辑参数" />
                <div v-else class="table-wrap">
                  <n-data-table :columns="optionColumns" :data="optionRows" :pagination="{ pageSize: 10 }" size="small" striped />
                </div>
              </n-tab-pane>

              <n-tab-pane v-if="showValuesTab" name="values" tab="敏感值池">
                <div class="panel-toolbar">
                  <n-button type="primary" secondary @click="openValueModal">
                    <template #icon><KeyRound :size="16" /></template>
                    新增敏感值
                  </n-button>
                </div>
                <div class="table-wrap">
                  <n-data-table :columns="valueColumns" :data="selectedItem.values" :pagination="{ pageSize: 10 }" size="small" striped />
                </div>
              </n-tab-pane>
            </n-tabs>
          </template>
        </section>
      </div>

    <n-modal v-model:show="optionModalOpen" preset="card" title="编辑参数" class="config-modal">
      <n-form label-placement="top" class="modal-form single">
        <n-form-item label="参数">
          <n-input :value="optionForm.option_name" disabled />
        </n-form-item>
        <n-form-item label="编码">
          <n-input :value="optionForm.option_key" disabled class="mono" />
        </n-form-item>
        <n-form-item label="值类型">
          <n-input :value="optionForm.value_type" disabled />
        </n-form-item>
        <n-form-item label="当前值">
          <n-input v-model:value="optionValueText" type="textarea" class="mono" :autosize="{ minRows: 3, maxRows: 10 }" />
        </n-form-item>
      </n-form>
      <template #footer>
        <n-space justify="end">
          <n-button @click="optionModalOpen = false">取消</n-button>
          <n-button type="primary" :loading="savingOptions" @click="saveOption">保存参数</n-button>
        </n-space>
      </template>
    </n-modal>

    <n-modal v-model:show="valueModalOpen" preset="card" title="新增敏感值" class="config-modal">
      <n-form label-placement="top" class="modal-form">
        <n-form-item label="名称">
          <n-input v-model:value="valueForm.value_name" />
        </n-form-item>
        <n-form-item label="类型">
          <n-select v-model:value="valueForm.value_kind" :options="valueKindOptions" />
        </n-form-item>
        <n-form-item :label="secretInputLabel">
          <n-input v-model:value="valueForm.secret" type="password" show-password-on="click" />
        </n-form-item>
        <n-form-item v-if="isEndpointValueConfig" label="专属 API URL" class="span-2">
          <n-input v-model:value="valueForm.endpoint_url" placeholder="留空则使用默认 API URL" />
        </n-form-item>
        <n-form-item label="运行时用途">
          <n-input :value="runtimePurposeLabel" disabled />
        </n-form-item>
        <n-form-item label="优先级">
          <n-input-number v-model:value="valueForm.priority" :min="1" :max="9999" />
        </n-form-item>
        <n-form-item label="权重">
          <n-input-number v-model:value="valueForm.weight" :min="1" :max="9999" />
        </n-form-item>
        <n-form-item label="启用">
          <n-switch v-model:value="valueForm.is_enabled" />
        </n-form-item>
        <n-form-item label="描述" class="span-2">
          <n-input v-model:value="valueForm.description" type="textarea" :autosize="{ minRows: 2, maxRows: 5 }" />
        </n-form-item>
        <n-alert class="span-2" type="warning" :bordered="false">敏感值只提交一次，保存后页面不会显示明文。</n-alert>
      </n-form>
      <template #footer>
        <n-space justify="end">
          <n-button @click="valueModalOpen = false">取消</n-button>
          <n-button type="primary" :loading="savingValue" @click="saveValue">保存</n-button>
        </n-space>
      </template>
    </n-modal>

    <n-modal v-model:show="valueEditOpen" preset="card" title="编辑敏感值" class="config-modal">
      <n-form label-placement="top" class="modal-form">
        <n-form-item label="名称">
          <n-input v-model:value="valueEditForm.value_name" />
        </n-form-item>
        <n-form-item :label="`替换 ${secretInputLabel}`">
          <n-input v-model:value="valueEditForm.secret" type="password" show-password-on="click" placeholder="留空则不修改" />
        </n-form-item>
        <n-form-item v-if="isEndpointValueConfig" label="专属 API URL" class="span-2">
          <n-input v-model:value="valueEditForm.endpoint_url" placeholder="留空则使用默认 API URL" />
        </n-form-item>
        <n-form-item label="优先级">
          <n-input-number v-model:value="valueEditForm.priority" :min="1" :max="9999" />
        </n-form-item>
        <n-form-item label="权重">
          <n-input-number v-model:value="valueEditForm.weight" :min="1" :max="9999" />
        </n-form-item>
        <n-form-item label="启用">
          <n-switch v-model:value="valueEditForm.is_enabled" />
        </n-form-item>
        <n-form-item label="描述" class="span-2">
          <n-input v-model:value="valueEditForm.description" type="textarea" :autosize="{ minRows: 2, maxRows: 5 }" />
        </n-form-item>
      </n-form>
      <template #footer>
        <n-space justify="end">
          <n-button @click="valueEditOpen = false">取消</n-button>
          <n-button type="primary" :loading="savingValue" @click="saveValueEdit">保存</n-button>
        </n-space>
      </template>
    </n-modal>
  </main>
</template>

<script setup lang="ts">
import { computed, h, onMounted, reactive, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { Bell, Bot, Database, Edit3, KeyRound, RefreshCw, Search } from 'lucide-vue-next';
import {
  NAlert,
  NBadge,
  NButton,
  NDataTable,
  NEmpty,
  NForm,
  NFormItem,
  NInput,
  NInputNumber,
  NModal,
  NSelect,
  NSpace,
  NSpin,
  NSwitch,
  NTabPane,
  NTabs,
  NTag,
  useDialog,
  useMessage,
  type DataTableColumns,
} from 'naive-ui';
import { configApi, type OptionPayload, type ValueCreatePayload } from '@/api/config';
import type { ConfigCategory, ConfigItem, ConfigOption, ConfigValue, SystemConfig } from '@/types/config';
import { formatTime, parseLooseValue, stringifyJson } from '@/utils/json';

const route = useRoute();
const router = useRouter();
const message = useMessage();
const dialog = useDialog();

const categories = [
  { value: 'search' as const, label: 'Search', icon: Search, description: '问财、妙想、Kimi Search 的共享 Key 池。' },
  { value: 'llm' as const, label: 'LLM', icon: Bot, description: '固定 LLM 模型配置、默认模型和 Key 池。' },
  { value: 'notification' as const, label: 'Notification', icon: Bell, description: '飞书、邮件、自定义 Webhook 的渠道配置。' },
  { value: 'market_data' as const, label: '数据源', icon: Database, description: 'Tushare Pro、TickFlow、Redis Cache 等数据源与运行参数。' },
];

const activeCategory = ref<ConfigCategory>(normalizeCategory(route.params.domain));
const activeTab = ref('basic');
const keyword = ref('');
const loading = ref(false);
const itemsByCategory = reactive<Record<ConfigCategory, ConfigItem[]>>({ search: [], llm: [], notification: [], market_data: [] });
const selectedItem = ref<ConfigItem | null>(null);
const summaryCounts = reactive({ search: 0, llm: 0, notification: 0, market_data: 0 });

const configForm = reactive({
  config_name: '',
  is_default: false,
  is_enabled: true,
  description: '',
});
const savingConfig = ref(false);

const optionModalOpen = ref(false);
const optionEditingIndex = ref<number | null>(null);
const savingOptions = ref(false);
const optionValueText = ref('');
const optionForm = reactive({ option_key: '', option_name: '', value_type: 'string' });

const valueModalOpen = ref(false);
const valueEditOpen = ref(false);
const savingValue = ref(false);
const valueForm = reactive({
  value_name: 'primary',
  value_kind: 'api_key',
  secret: '',
  endpoint_url: '',
  priority: 100,
  weight: 100,
  is_enabled: true,
  description: '',
});
const valueEditId = ref<number | null>(null);
const valueEditForm = reactive({
  value_name: '',
  secret: '',
  endpoint_url: '',
  priority: 100,
  weight: 100,
  is_enabled: true,
  description: '',
});

const valueKindOptions = computed(() => {
  if (activeCategory.value === 'market_data' && selectedItem.value?.config.config_code === 'redis_cache') return [{ label: 'redis_url', value: 'redis_url' }];
  if (activeCategory.value === 'market_data' && selectedItem.value?.config.config_code === 'tickflow') return [{ label: 'api_key', value: 'api_key' }];
  if (activeCategory.value === 'market_data') return [{ label: 'token', value: 'token' }];
  if (activeCategory.value !== 'notification') return [{ label: 'api_key', value: 'api_key' }];
  if (selectedItem.value?.config.config_code === 'email') return [{ label: 'smtp_password', value: 'smtp_password' }];
  return [
    { label: 'webhook_url', value: 'webhook_url' },
    { label: 'token', value: 'token' },
    { label: 'credential_json', value: 'credential_json' },
  ];
});

const activeCategoryMeta = computed(() => categories.find((item) => item.value === activeCategory.value) || categories[0]);
const activeItems = computed(() => itemsByCategory[activeCategory.value]);
const isTushareTokenConfig = computed(() => activeCategory.value === 'market_data' && selectedItem.value?.config.config_code === 'tushare_pro');
const isTickflowApiConfig = computed(() => activeCategory.value === 'market_data' && selectedItem.value?.config.config_code === 'tickflow');
const isEndpointValueConfig = computed(() => isTushareTokenConfig.value || isTickflowApiConfig.value);
const isRedisCacheConfig = computed(() => activeCategory.value === 'market_data' && selectedItem.value?.config.config_code === 'redis_cache');
const optionsTabLabel = computed(() => activeCategory.value === 'llm' ? '模型参数' : activeCategory.value === 'market_data' ? '数据源参数' : '渠道参数');
const categoryCounts = computed(() => ({
  search: summaryCounts.search || itemsByCategory.search.length,
  llm: summaryCounts.llm || itemsByCategory.llm.length,
  notification: summaryCounts.notification || itemsByCategory.notification.length,
  market_data: summaryCounts.market_data || itemsByCategory.market_data.length,
}));
const filteredItems = computed(() => {
  const needle = keyword.value.trim().toLowerCase();
  if (!needle) return activeItems.value;
  return activeItems.value.filter((item) =>
    [item.config.config_name, item.config.config_code].some((value) => value.toLowerCase().includes(needle)),
  );
});
const showOptionsTab = computed(() => activeCategory.value !== 'search');
const showValuesTab = computed(() => activeCategory.value !== 'notification');
const optionRows = computed(() => (selectedItem.value?.options || []).map((option, index) => ({ ...option, rowIndex: index })));
const optionHelperText = computed(() => {
  if (isRedisCacheConfig.value) return 'Redis URL 放在敏感值池；这里只维护缓存后端、Key 前缀、超时和数据中心缓存 TTL。';
  if (isTickflowApiConfig.value) return 'TickFlow 仅用于实时 Quote；MooTDX 继续负责实时分钟线。专属 URL 留空即可使用 SDK 默认入口。';
  if (activeCategory.value === 'market_data') return '默认 API URL 仅供未设置专属 URL 的 Token 使用。';
  if (activeCategory.value === 'notification') return '通知渠道参数直接在这里维护，包括 Webhook URL、SMTP Password 和 Token。';
  return '这里只编辑非敏感模型参数；API Key 放在敏感值池。';
});
const secretInputLabel = computed(() => {
  if (isRedisCacheConfig.value) return 'Redis URL';
  if (isTushareTokenConfig.value) return 'Token';
  if (isTickflowApiConfig.value) return 'TickFlow API Key';
  return 'API Key / Secret';
});
const runtimePurposeLabel = computed(() => {
  const code = selectedItem.value?.config.config_code;
  if (code === 'iwencai_search') return '问财 Skill 入口';
  if (code === 'miaoxiang_search') return '妙想 Skill 入口';
  if (code === 'kimi_search') return 'Kimi Web Search';
  if (activeCategory.value === 'llm') return 'LLM 调用入口';
  if (code === 'tushare_pro') return 'Tushare Pro 行情与专题数据入口';
  if (code === 'tickflow') return '实时 Quote 入口（分钟线仍由 MooTDX 提供）';
  if (code === 'redis_cache') return '数据中心缓存与通用运行时缓存';
  if (code === 'feishu') return '飞书 Webhook';
  if (code === 'email') return 'SMTP Password';
  if (code === 'webhook') return 'Webhook URL / Token';
  return '内部运行时';
});

const optionColumns: DataTableColumns<ConfigOption & { rowIndex: number }> = [
  { title: '参数', key: 'option_name', width: 180, ellipsis: { tooltip: true } },
  { title: '编码', key: 'option_key', width: 180, ellipsis: { tooltip: true }, className: 'mono' },
  { title: '当前值', key: 'value', ellipsis: { tooltip: true }, render: (row) => valuePreview(row.value) },
  { title: '类型', key: 'value_type', width: 90 },
  { title: '状态', key: 'is_enabled', width: 90, render: (row) => statusTag(row.is_enabled) },
  {
    title: '操作',
    key: 'actions',
    width: 90,
    render(row) {
      return h(NButton, { size: 'tiny', secondary: true, onClick: () => openOptionModal(row.rowIndex) }, { icon: () => h(Edit3, { size: 14 }) });
    },
  },
];

const valueColumns = computed<DataTableColumns<ConfigValue>>(() => {
  const columns: DataTableColumns<ConfigValue> = [
  { title: 'ID', key: 'id', width: 70 },
  { title: '名称', key: 'value_name', width: 140, ellipsis: { tooltip: true } },
  { title: '类型', key: 'value_kind', width: 130, ellipsis: { tooltip: true } },
  { title: 'Fingerprint', key: 'fingerprint', width: 170, ellipsis: { tooltip: true }, className: 'mono' },
  { title: 'P/W', key: 'priority', width: 80, render: (row) => `${row.priority}/${row.weight}` },
  { title: '状态', key: 'status', width: 100, render: (row) => statusTag(row.status === 'active' && row.is_enabled, row.status) },
  { title: '失败', key: 'failure_count', width: 70 },
  { title: '最后使用', key: 'last_used_at', width: 170, render: (row) => formatTime(row.last_used_at) },
  {
    title: '操作',
    key: 'actions',
    width: 250,
    render(row) {
      const enabled = isValueEnabled(row);
      return h(NSpace, { size: 6 }, () => [
        h(NButton, { size: 'tiny', secondary: true, onClick: () => openValueEdit(row) }, { default: () => '编辑' }),
        h(NButton, { size: 'tiny', secondary: true, onClick: () => testValue(row) }, { default: () => '测试' }),
        h(
          NButton,
          {
            size: 'tiny',
            secondary: true,
            type: enabled ? 'warning' : 'success',
            onClick: () => (enabled ? disableValue(row) : enableValue(row)),
          },
          { default: () => (enabled ? '停用' : '启用') },
        ),
        h(NButton, { size: 'tiny', secondary: true, type: 'error', onClick: () => deleteValue(row) }, { default: () => '删除' }),
      ]);
    },
  },
  ];
  if (isEndpointValueConfig.value) {
    columns.splice(4, 0, {
      title: '生效入口',
      key: 'endpoint_url',
      width: 220,
      ellipsis: { tooltip: true },
      render: (row) => row.endpoint_url || '使用默认 URL',
    });
  }
  return columns;
});

watch(
  () => route.params.domain,
  (domain) => {
    activeCategory.value = normalizeCategory(domain);
  },
);

watch(activeCategory, async () => {
  activeTab.value = 'basic';
  selectedItem.value = null;
  await loadCategory(activeCategory.value);
  selectFirstItem();
});

onMounted(async () => {
  await loadSummary();
  await Promise.all(categories.map((category) => loadCategory(category.value)));
  selectFirstItem();
});

function normalizeCategory(value: unknown): ConfigCategory {
  return value === 'llm' || value === 'notification' || value === 'search' || value === 'market_data' ? value : 'search';
}

function switchCategory(category: ConfigCategory) {
  router.push(`/config/${category}`);
}

async function loadSummary() {
  try {
    const summary = await configApi.summary();
    summaryCounts.search = summary.categories.search || 0;
    summaryCounts.llm = summary.categories.llm || 0;
    summaryCounts.notification = summary.categories.notification || 0;
    summaryCounts.market_data = summary.categories.market_data || 0;
  } catch {
    // Domain item endpoints are the source of truth.
  }
}

async function loadCategory(category: ConfigCategory) {
  loading.value = true;
  try {
    itemsByCategory[category] = await configApi.items(category);
    if (category === activeCategory.value && !selectedItem.value) selectFirstItem();
  } catch (error) {
    message.error(errorMessage(error, '加载配置失败'));
  } finally {
    loading.value = false;
  }
}

async function reloadActive() {
  const selectedId = selectedItem.value?.config.id || null;
  await loadSummary();
  await loadCategory(activeCategory.value);
  selectItem(selectedId || activeItems.value[0]?.config.id || null);
}

function selectFirstItem() {
  selectItem(activeItems.value[0]?.config.id || null);
}

function selectItem(configId: number | null) {
  if (configId === null) return;
  const item = activeItems.value.find((candidate) => candidate.config.id === configId) || activeItems.value[0] || null;
  selectedItem.value = item;
  if (item) resetConfigForm(item.config);
}

function resetConfigForm(config: SystemConfig) {
  configForm.config_name = config.config_name;
  configForm.is_default = config.is_default;
  configForm.is_enabled = config.is_enabled;
  configForm.description = config.description || '';
}

async function saveConfig() {
  if (!selectedItem.value) return;
  savingConfig.value = true;
  try {
    await configApi.updateItem(selectedItem.value.config.id, {
      config_name: configForm.config_name,
      description: configForm.description || null,
      is_default: configForm.is_default,
      is_enabled: configForm.is_enabled,
    });
    await reloadActive();
    message.success('基本信息已保存');
  } catch (error) {
    message.error(errorMessage(error, '保存基本信息失败'));
  } finally {
    savingConfig.value = false;
  }
}

function openOptionModal(index: number) {
  const option = selectedItem.value?.options[index];
  if (!option) return;
  optionEditingIndex.value = index;
  optionForm.option_key = option.option_key;
  optionForm.option_name = option.option_name;
  optionForm.value_type = option.value_type;
  optionValueText.value = stringifyJson(option.value ?? '');
  optionModalOpen.value = true;
}

async function saveOption() {
  if (!selectedItem.value || optionEditingIndex.value === null) return;
  savingOptions.value = true;
  try {
    const next = selectedItem.value.options.map(toOptionPayload);
    const option = selectedItem.value.options[optionEditingIndex.value];
    next[optionEditingIndex.value] = {
      ...toOptionPayload(option),
      value: parseLooseValue(optionValueText.value, option.value_type),
    };
    await configApi.putOptions(selectedItem.value.config.id, next);
    optionModalOpen.value = false;
    await reloadActive();
    message.success('参数已保存');
  } catch (error) {
    message.error(errorMessage(error, '保存参数失败'));
  } finally {
    savingOptions.value = false;
  }
}

function toOptionPayload(option: ConfigOption): OptionPayload {
  return {
    option_key: option.option_key,
    option_name: option.option_name,
    value_type: option.value_type,
    value: option.value,
    default_value: option.default_value,
    is_required: option.is_required,
    is_enabled: option.is_enabled,
    description: option.description,
    metadata: option.metadata || {},
  };
}

function openValueModal() {
  valueForm.value_name = defaultValueName();
  valueForm.value_kind = defaultValueKind();
  valueForm.secret = '';
  valueForm.endpoint_url = '';
  valueForm.priority = 100;
  valueForm.weight = 100;
  valueForm.is_enabled = true;
  valueForm.description = '';
  valueModalOpen.value = true;
}

async function saveValue() {
  if (!selectedItem.value) return;
  if (!valueForm.secret.trim()) {
    message.warning(`请输入${secretInputLabel.value}`);
    return;
  }
  savingValue.value = true;
  try {
    const payload: ValueCreatePayload = {
      value_name: valueForm.value_name,
      value_kind: valueForm.value_kind,
      secret: valueForm.secret,
      endpoint_url: isEndpointValueConfig.value ? (valueForm.endpoint_url.trim() || null) : undefined,
      priority: valueForm.priority,
      weight: valueForm.weight,
      status: valueForm.is_enabled ? 'active' : 'disabled',
      is_enabled: valueForm.is_enabled,
      description: valueForm.description || null,
      metadata: {},
    };
    await configApi.createValue(selectedItem.value.config.id, payload);
    valueForm.secret = '';
    valueModalOpen.value = false;
    await reloadActive();
    message.success('敏感值已保存');
  } catch (error) {
    message.error(errorMessage(error, '保存敏感值失败'));
  } finally {
    savingValue.value = false;
  }
}

function openValueEdit(row: ConfigValue) {
  valueEditId.value = row.id;
  valueEditForm.value_name = row.value_name;
  valueEditForm.secret = '';
  valueEditForm.endpoint_url = row.endpoint_url || '';
  valueEditForm.priority = row.priority;
  valueEditForm.weight = row.weight;
  valueEditForm.is_enabled = row.is_enabled;
  valueEditForm.description = row.description || '';
  valueEditOpen.value = true;
}

async function saveValueEdit() {
  if (valueEditId.value === null) return;
  savingValue.value = true;
  try {
    await configApi.updateValue(valueEditId.value, {
      value_name: valueEditForm.value_name,
      status: valueEditForm.is_enabled ? 'active' : 'disabled',
      ...(valueEditForm.secret.trim() ? { secret: valueEditForm.secret.trim() } : {}),
      ...(isEndpointValueConfig.value ? { endpoint_url: valueEditForm.endpoint_url.trim() || null } : {}),
      priority: valueEditForm.priority,
      weight: valueEditForm.weight,
      is_enabled: valueEditForm.is_enabled,
      description: valueEditForm.description || null,
    });
    valueEditForm.secret = '';
    valueEditForm.endpoint_url = '';
    valueEditOpen.value = false;
    await reloadActive();
    message.success('敏感值已更新');
  } catch (error) {
    message.error(errorMessage(error, '更新敏感值失败'));
  } finally {
    savingValue.value = false;
  }
}

function isValueEnabled(row: ConfigValue): boolean {
  return row.status === 'active' && row.is_enabled;
}

function enableValue(row: ConfigValue) {
  dialog.success({
    title: '启用敏感值',
    content: `确认启用 "${row.value_name}"？它会重新加入运行时凭据池。`,
    positiveText: '启用',
    negativeText: '取消',
    onPositiveClick: async () => {
      await configApi.updateValue(row.id, {
        status: 'active',
        is_enabled: true,
        cooldown_until: null,
      });
      await reloadActive();
      message.success('敏感值已启用');
    },
  });
}

function disableValue(row: ConfigValue) {
  dialog.warning({
    title: '停用敏感值',
    content: `确认停用 "${row.value_name}"？`,
    positiveText: '停用',
    negativeText: '取消',
    onPositiveClick: async () => {
      await configApi.disableValue(row.id);
      await reloadActive();
      message.success('敏感值已停用');
    },
  });
}

function deleteValue(row: ConfigValue) {
  dialog.error({
    title: '删除敏感值',
    content: `确认删除 "${row.value_name}"？删除后不会显示或参与调用，需要重新新增才能恢复。`,
    positiveText: '删除',
    negativeText: '取消',
    onPositiveClick: async () => {
      await configApi.deleteValue(row.id);
      await reloadActive();
      message.success('敏感值已删除');
    },
  });
}

async function testValue(row: ConfigValue) {
  try {
    const result = await configApi.testValue(row.id);
    if (result.available) {
      const isTushareToken = activeCategory.value === 'market_data' && selectedItem.value?.config.config_code === 'tushare_pro';
      const isRedisUrl = activeCategory.value === 'market_data' && selectedItem.value?.config.config_code === 'redis_cache';
      const isTickflowApi = activeCategory.value === 'market_data' && selectedItem.value?.config.config_code === 'tickflow';
      message.success(isTushareToken ? 'Tushare 日线连通性正常' : isTickflowApi ? 'TickFlow Quote 连通性正常' : isRedisUrl ? 'Redis 连接正常' : `敏感值可用：${result.fingerprint}`);
    }
    else message.warning(`敏感值不可用：${result.error || result.status}`);
  } catch (error) {
    message.error(errorMessage(error, '测试敏感值失败'));
  }
}

function defaultValueKind(): string {
  if (activeCategory.value === 'market_data' && selectedItem.value?.config.config_code === 'redis_cache') return 'redis_url';
  if (activeCategory.value === 'market_data' && selectedItem.value?.config.config_code === 'tickflow') return 'api_key';
  if (activeCategory.value === 'market_data') return 'token';
  if (activeCategory.value !== 'notification') return 'api_key';
  if (selectedItem.value?.config.config_code === 'email') return 'smtp_password';
  return 'webhook_url';
}

function defaultValueName(): string {
  if (activeCategory.value === 'market_data' && selectedItem.value?.config.config_code === 'redis_cache') return 'redis_connection';
  if (activeCategory.value === 'market_data' && selectedItem.value?.config.config_code === 'tickflow') return 'tickflow_api_key';
  if (activeCategory.value === 'market_data') return 'tushare_token';
  if (activeCategory.value === 'notification') return defaultValueKind();
  return 'primary';
}

function statusTag(ok: boolean, label?: string) {
  return h(
    NTag,
    { size: 'small', type: ok ? 'success' : 'warning', bordered: false },
    { default: () => label || (ok ? 'enabled' : 'disabled') },
  );
}

function valuePreview(value: unknown): string {
  if (value === null || value === undefined || value === '') return '-';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}
</script>

<style scoped>
.config-page {
  min-width: 0;
  padding: 20px;
}

.detail-head,
.panel-toolbar,
.actions-row,
.title-row {
  display: flex;
  align-items: center;
  gap: 12px;
}

.topbar {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  margin-bottom: 16px;
}

.topbar h1,
.title-row h2 {
  margin: 0;
}

.topbar h1 {
  font-size: 24px;
  line-height: 1.25;
}

.topbar p {
  margin: 6px 0 0;
  color: #64748b;
}

.category-strip {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 16px;
}

.category-item {
  min-height: 38px;
  border: 1px solid #dbe3ea;
  border-radius: 6px;
  padding: 0 12px;
  display: grid;
  grid-template-columns: 20px auto auto;
  align-items: center;
  gap: 8px;
  color: #334155;
  background: #fff;
  text-align: left;
  cursor: pointer;
}

.category-item:hover,
.category-item.active {
  border-color: #1f8a70;
  color: #145c4a;
  background: #f4fbf8;
}

.content-grid {
  display: grid;
  grid-template-columns: minmax(260px, 340px) minmax(0, 1fr);
  gap: 16px;
  align-items: start;
}

.object-panel,
.detail-panel {
  background: #fff;
  border: 1px solid #dbe3ea;
  border-radius: 8px;
  padding: 14px;
}

.object-panel {
  display: grid;
  gap: 12px;
  max-height: calc(100vh - 110px);
  overflow: auto;
}

.panel-title {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-weight: 700;
}

.object-item {
  width: 100%;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  background: #fff;
  padding: 10px;
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 8px;
  text-align: left;
  cursor: pointer;
}

.object-list {
  display: grid;
  gap: 8px;
}

.object-item:hover,
.object-item.active {
  border-color: #1f8a70;
  background: #f4fbf8;
}

.object-main {
  min-width: 0;
  display: grid;
  gap: 3px;
}

.object-main span {
  font-weight: 650;
}

.object-main code,
.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}

.object-main code,
.muted {
  color: #64748b;
}

.object-meta {
  display: flex;
  gap: 4px;
  align-items: flex-start;
  flex-wrap: wrap;
}

.detail-panel {
  min-width: 0;
}

.detail-head {
  justify-content: space-between;
  margin-bottom: 12px;
}

.title-row {
  flex-wrap: wrap;
}

.title-row h2 {
  font-size: 20px;
}

.metric-row {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  margin: 12px 0 16px;
}

.metric {
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 10px;
  display: grid;
  gap: 4px;
}

.metric span {
  color: #64748b;
  font-size: 12px;
}

.metric strong {
  font-size: 20px;
  word-break: break-word;
}

.basic-form,
.modal-form {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px 14px;
}

.modal-form.single {
  grid-template-columns: minmax(0, 1fr);
}

.span-2 {
  grid-column: 1 / -1;
}

.helper-line {
  color: #64748b;
  font-size: 13px;
  margin-bottom: 10px;
}

.table-wrap {
  min-width: 0;
  overflow-x: auto;
}

.config-modal {
  width: min(760px, calc(100vw - 24px));
}

@media (max-width: 860px) {
  .content-grid,
  .metric-row,
  .basic-form,
  .modal-form {
    grid-template-columns: 1fr;
  }

  .span-2 {
    grid-column: auto;
  }
}
</style>
