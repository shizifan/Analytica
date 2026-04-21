import { useSlotStore } from '../../../stores/slotStore';
import { Icon } from '../Icon';
import type { SlotState } from '../../../types';

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

const SOURCE_TAG: Record<string, string> = {
  user_input: 'USER',
  memory: 'MEM',
  memory_low_confidence: 'MEM·L',
  inferred: 'INF',
  default: 'DEF',
  history: 'HIST',
};

function classFor(slot: SlotState, asking: boolean): string {
  const base = 'an-slot-row';
  if (asking) return `${base} asking`;
  if (slot.value === null || slot.value === undefined || slot.value === '') {
    return base;
  }
  if (slot.source === 'memory' || slot.source === 'memory_low_confidence') return `${base} memory`;
  if (slot.source === 'inferred' || slot.source === 'default') return `${base} inferred`;
  return `${base} filled`;
}

function formatValue(v: unknown): string {
  if (v === null || v === undefined || v === '') return '—';
  if (typeof v === 'object') return JSON.stringify(v);
  return String(v);
}

/**
 * Phase 3.5 — Slot status rendered with new design tokens (replaces the
 * v1 Tailwind card that was shown inside the Inspector until now).
 */
export function StatusTab() {
  const slots = useSlotStore((s) => s.slots);
  const currentAsking = useSlotStore((s) => s.currentAsking);
  const entries = Object.entries(slots);

  const requiredFilled = [...REQUIRED_SLOTS].every(
    (n) => slots[n]?.value != null && slots[n].value !== '',
  );

  if (entries.length === 0) {
    return (
      <div className="an-thinking-empty">
        等待槽位填充…
        <br />
        <span className="an-mono" style={{ fontSize: 10, color: 'var(--an-ink-5)' }}>
          感知阶段尚未开始
        </span>
      </div>
    );
  }

  // Group required first, then the rest — keeps user eye on the must-haves.
  const required = entries.filter(([k]) => REQUIRED_SLOTS.has(k));
  const optional = entries.filter(([k]) => !REQUIRED_SLOTS.has(k));

  return (
    <div className="an-slot-group" data-testid="slot-status-card">
      {requiredFilled && (
        <div className="an-slot-summary" data-testid="slot-complete-banner">
          <Icon name="check" size={12} />
          信息完整 · 必填 {REQUIRED_SLOTS.size}/{REQUIRED_SLOTS.size}
        </div>
      )}

      {required.length > 0 && (
        <>
          <div className="an-slot-section-label">必填</div>
          {required.map(([name, slot]) => (
            <SlotRow
              key={name}
              name={name}
              slot={slot}
              asking={currentAsking === name}
            />
          ))}
        </>
      )}

      {optional.length > 0 && (
        <>
          <div className="an-slot-section-label">可选 / 推断</div>
          {optional.map(([name, slot]) => (
            <SlotRow
              key={name}
              name={name}
              slot={slot}
              asking={currentAsking === name}
            />
          ))}
        </>
      )}
    </div>
  );
}

function SlotRow({
  name,
  slot,
  asking,
}: {
  name: string;
  slot: SlotState;
  asking: boolean;
}) {
  const label = SLOT_LABELS[name] ?? name;
  const value = formatValue(slot.value);
  const srcTag = SOURCE_TAG[slot.source] ?? slot.source.toUpperCase();
  return (
    <div
      className={classFor(slot, asking)}
      data-testid={`slot-${name}`}
      data-source={slot.source}
      data-value={typeof slot.value === 'string' ? slot.value : undefined}
      data-confidence-low={slot.source === 'memory_low_confidence' ? 'true' : undefined}
      title={value.length > 40 ? value : undefined}
    >
      <span className="an-slot-name">{label}</span>
      <span className="an-slot-value">{value}</span>
      {slot.value != null && slot.value !== '' && (
        <span className="an-slot-source">{srcTag}</span>
      )}
    </div>
  );
}
