export function stringifyJson(value: unknown): string {
  if (value === null || value === undefined) return '';
  if (typeof value === 'string') return value;
  return JSON.stringify(value, null, 2);
}

export function parseLooseValue(text: string, valueType: string): unknown {
  const trimmed = text.trim();
  if (valueType === 'number') return trimmed === '' ? null : Number(trimmed);
  if (valueType === 'int' || valueType === 'integer') return trimmed === '' ? null : Number.parseInt(trimmed, 10);
  if (valueType === 'bool' || valueType === 'boolean') return trimmed === 'true';
  if (valueType === 'json' || valueType === 'object' || valueType === 'array') return trimmed ? JSON.parse(trimmed) : {};
  return text;
}

export function parseJsonObject(text: string, fallback: Record<string, unknown> = {}): Record<string, unknown> {
  const trimmed = text.trim();
  if (!trimmed) return fallback;
  const parsed = JSON.parse(trimmed);
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new Error('必须是 JSON object');
  }
  return parsed as Record<string, unknown>;
}

export function formatTime(value: string | null | undefined): string {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString('zh-CN', { hour12: false });
}
