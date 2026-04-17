import { useSlotStore } from '../stores/slotStore';
import type { SlotState } from '../types';

const SLOT_LABELS: Record<string, string> = {
  analysis_subject: '分析对象',
  time_range: '时间范围',
  output_complexity: '复杂度',
  output_format: '输出格式',
  attribution_needed: '归因分析',
  predictive_needed: '预测分析',
  time_granularity: '时间粒度',
  domain: '业务领域',
  comparison_type: '对比方式',
  region: '区域',
  data_granularity: '数据粒度',
  domain_glossary: '业务术语',
};

const REQUIRED_SLOTS = new Set(['analysis_subject', 'time_range', 'output_complexity']);

function slotColorByName(name: string, slot: SlotState): string {
  if (!slot.value) {
    return REQUIRED_SLOTS.has(name) ? 'border-red-400 bg-red-50' : 'border-gray-300 bg-gray-50';
  }
  if (slot.source === 'memory') return 'border-blue-400 bg-blue-50';
  if (slot.source === 'memory_low_confidence') return 'border-orange-400 bg-orange-50';
  return 'border-green-400 bg-green-50';
}

function formatValue(v: unknown): string {
  if (v === null || v === undefined) return '';
  if (typeof v === 'object') return JSON.stringify(v);
  return String(v);
}

export function SlotStatusCard() {
  const slots = useSlotStore((s) => s.slots);
  const currentAsking = useSlotStore((s) => s.currentAsking);
  const entries = Object.entries(slots);

  const allRequiredFilled = [...REQUIRED_SLOTS].every((name) => {
    const s = slots[name];
    return s && s.value != null;
  });

  return (
    <div data-testid="slot-status-card" className="rounded-lg border border-gray-200 bg-white p-3">
      <h3 className="mb-2 text-sm font-semibold text-gray-700">Slot 填充状态</h3>

      {allRequiredFilled && entries.length > 0 && (
        <div data-testid="slot-complete-banner"
          className="mb-2 rounded bg-green-100 px-2 py-1 text-xs font-medium text-green-700 transition-opacity">
          &#10003; 信息完整
        </div>
      )}

      {entries.length === 0 && (
        <p className="text-xs text-gray-400">等待分析开始...</p>
      )}

      <ul className="space-y-1">
        {entries.map(([name, slot]) => {
          const label = SLOT_LABELS[name] ?? name;
          const asking = currentAsking === name;
          const val = formatValue(slot.value);
          const badge = slot.source === 'memory' ? '来自记忆'
            : slot.source === 'memory_low_confidence' ? '低置信度'
            : slot.value == null && REQUIRED_SLOTS.has(name) ? '待填写'
            : slot.value == null ? '可选' : '';

          return (
            <li key={name}
              data-testid={`slot-${name}`}
              data-source={slot.source}
              data-value={typeof slot.value === 'string' ? slot.value : undefined}
              data-confidence-low={slot.source === 'memory_low_confidence' ? 'true' : undefined}
              className={`flex items-center justify-between rounded border px-2 py-1 text-xs ${slotColorByName(name, slot)} ${asking ? 'ring-2 ring-blue-400' : ''}`}
            >
              <span className="font-medium text-gray-700">{label}</span>
              <span className="flex items-center gap-1">
                {val && <span className="max-w-[120px] truncate text-gray-600">{val}</span>}
                {badge && (
                  <span className={`rounded px-1 text-[10px] ${
                    badge === '来自记忆' ? 'bg-blue-200 text-blue-700'
                    : badge === '低置信度' ? 'bg-orange-200 text-orange-700'
                    : badge === '待填写' ? 'bg-red-200 text-red-700'
                    : 'bg-gray-200 text-gray-500'
                  }`}>{badge}</span>
                )}
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
