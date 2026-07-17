<template>
  <n-form label-placement="top" class="payload-form">
    <n-form-item v-for="entry in entries" :key="entry.key" :label="entry.spec.label || entry.key">
      <div class="payload-field">
        <n-select
          v-if="entry.spec.type === 'string' && entry.options.length"
          :value="stringValue(entry.key)"
          :options="entry.options"
          @update:value="updateValue(entry.key, $event)"
        />
        <n-input
          v-else-if="entry.spec.type === 'string'"
          :value="stringValue(entry.key)"
          @update:value="updateValue(entry.key, $event)"
        />
        <n-input-number
          v-else-if="entry.spec.type === 'number'"
          :value="numberValue(entry.key)"
          :min="entry.spec.min"
          :max="entry.spec.max"
          :show-button="true"
          @update:value="updateValue(entry.key, $event)"
        />
        <n-switch
          v-else-if="entry.spec.type === 'boolean'"
          :value="Boolean(modelValue[entry.key])"
          @update:value="updateValue(entry.key, $event)"
        >
          <template #checked>启用</template>
          <template #unchecked>关闭</template>
        </n-switch>
        <n-checkbox-group
          v-else-if="entry.spec.type === 'array'"
          :value="arrayValue(entry.key)"
          @update:value="updateValue(entry.key, $event)"
        >
          <n-space wrap>
            <n-checkbox v-for="option in entry.spec.options || []" :key="String(option)" :value="String(option)">
              {{ option }}
            </n-checkbox>
          </n-space>
        </n-checkbox-group>
        <n-input
          v-else-if="entry.spec.type === 'json'"
          :value="jsonValue(entry.key)"
          type="textarea"
          class="mono"
          :status="jsonErrors[entry.key] ? 'error' : undefined"
          :autosize="{ minRows: 4, maxRows: 10 }"
          @update:value="updateJson(entry.key, $event)"
        />
        <span v-else class="unsupported-field">不支持的参数类型：{{ entry.spec.type || 'unknown' }}</span>
        <small v-if="entry.spec.description">{{ entry.spec.description }}</small>
        <small v-if="jsonErrors[entry.key]" class="field-error">{{ jsonErrors[entry.key] }}</small>
      </div>
    </n-form-item>
  </n-form>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { NCheckbox, NCheckboxGroup, NForm, NFormItem, NInput, NInputNumber, NSelect, NSpace, NSwitch } from 'naive-ui';
import type { SchedulerParameterSchema, SchedulerParameterSpec } from '@/types/scheduler';
import { stringifyJson } from '@/utils/json';

const props = defineProps<{
  modelValue: Record<string, unknown>;
  schema: SchedulerParameterSchema;
}>();

const emit = defineEmits<{
  'update:modelValue': [value: Record<string, unknown>];
  'validity-change': [valid: boolean];
}>();

const jsonTexts = ref<Record<string, string>>({});
const jsonErrors = ref<Record<string, string>>({});
const entries = computed(() => Object.entries(props.schema).map(([key, spec]) => ({ key, spec, options: optionsFor(spec) })));

watch(
  () => [props.modelValue, props.schema] as const,
  () => {
    const next: Record<string, string> = {};
    for (const [key, spec] of Object.entries(props.schema)) {
      if (spec.type === 'json') next[key] = stringifyJson(props.modelValue[key] ?? spec.default ?? {});
    }
    jsonTexts.value = next;
    jsonErrors.value = {};
  },
  { immediate: true, deep: true },
);

watch(
  jsonErrors,
  (errors) => emit('validity-change', !Object.values(errors).some(Boolean)),
  { deep: true },
);

function updateValue(key: string, value: unknown) {
  emit('update:modelValue', { ...props.modelValue, [key]: value });
}

function updateJson(key: string, value: string) {
  jsonTexts.value = { ...jsonTexts.value, [key]: value };
  try {
    const parsed = value.trim() ? JSON.parse(value) : {};
    jsonErrors.value = { ...jsonErrors.value, [key]: '' };
    updateValue(key, parsed);
  } catch {
    jsonErrors.value = { ...jsonErrors.value, [key]: '请输入有效 JSON' };
  }
}

function stringValue(key: string) {
  const value = props.modelValue[key];
  return value === undefined || value === null ? '' : String(value);
}

function numberValue(key: string) {
  const value = props.modelValue[key];
  return typeof value === 'number' ? value : null;
}

function arrayValue(key: string) {
  const value = props.modelValue[key];
  return Array.isArray(value) ? value : [];
}

function jsonValue(key: string) {
  return jsonTexts.value[key] || '';
}

function optionsFor(spec: SchedulerParameterSpec) {
  return (spec.options || [])
    .filter((option): option is string | number => typeof option === 'string' || typeof option === 'number')
    .map((option) => ({ label: String(option), value: option }));
}
</script>

<style scoped>
.payload-form { min-width: 0; }
.payload-field { width: 100%; display: grid; gap: 7px; }
.payload-field small { color: #64748b; line-height: 1.45; }
.field-error { color: #c2410c !important; }
.unsupported-field { color: #c2410c; font-size: 13px; }
</style>
