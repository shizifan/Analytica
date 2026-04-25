import { useSlotStore } from '../../../stores/slotStore';
import { Icon } from '../Icon';
import type { SlotState } from '../../../types';
import { SmartValue, SourceTag } from './_primitives';

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
  business_type: '业务类型',
  cargo_type: '货类',
  asset_category: '资产类别',
  project_type: '项目类型',
  project_status: '项目状态',
  equipment_type: '设备分类',
};

const REQUIRED_SLOTS = new Set(['analysis_subject', 'time_range', 'output_complexity']);

function isFilled(slot: SlotState): boolean {
  const v = slot.value;
  return v !== null && v !== undefined && v !== '' &&
    !(Array.isArray(v) && v.length === 0);
}

function rowClass(slot: SlotState, asking: boolean, filled: boolean): string {
  const base = 'an-slot-row-v2';
  if (asking) return `${base} asking`;
  if (!filled) return `${base} empty`;
  if (slot.source === 'memory' || slot.source === 'memory_low_confidence') return `${base} memory`;
  if (slot.source === 'inferred' || slot.source === 'default') return `${base} inferred`;
  return `${base} filled`;
}

export function StatusTab() {
  const slots = useSlotStore((s) => s.slots);
  const currentAsking = useSlotStore((s) => s.currentAsking);
  const entries = Object.entries(slots);

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

  const requiredFilled = [...REQUIRED_SLOTS].every(
    (n) => slots[n] && isFilled(slots[n]),
  );

  // Group: required (always show), then filled-optional, then empty-optional.
  const required = entries.filter(([k]) => REQUIRED_SLOTS.has(k));
  const optional = entries.filter(([k]) => !REQUIRED_SLOTS.has(k));
  const optFilled = optional.filter(([, s]) => isFilled(s));
  const optEmpty = optional.filter(([, s]) => !isFilled(s));

  return (
    <div className="an-slot-group-v2" data-testid="slot-status-card">
      {requiredFilled && (
        <div className="an-slot-summary" data-testid="slot-complete-banner">
          <Icon name="check" size={12} />
          信息完整 · 必填 {REQUIRED_SLOTS.size}/{REQUIRED_SLOTS.size}
        </div>
      )}

      {required.length > 0 && (
        <Section title={`必填 · ${required.filter(([, s]) => isFilled(s)).length}/${required.length}`}>
          {required.map(([name, slot]) => (
            <SlotRow
              key={name}
              name={name}
              slot={slot}
              asking={currentAsking === name}
            />
          ))}
        </Section>
      )}

      {optFilled.length > 0 && (
        <Section title={`已填 · ${optFilled.length}`}>
          {optFilled.map(([name, slot]) => (
            <SlotRow
              key={name}
              name={name}
              slot={slot}
              asking={currentAsking === name}
            />
          ))}
        </Section>
      )}

      {optEmpty.length > 0 && (
        <Section title={`未填 · ${optEmpty.length}`} muted>
          {optEmpty.map(([name, slot]) => (
            <SlotRow
              key={name}
              name={name}
              slot={slot}
              asking={currentAsking === name}
            />
          ))}
        </Section>
      )}
    </div>
  );
}

function Section({
  title,
  children,
  muted = false,
}: {
  title: string;
  children: React.ReactNode;
  muted?: boolean;
}) {
  return (
    <div className={`an-slot-section${muted ? ' is-muted' : ''}`}>
      <div className="an-slot-section-label-v2">{title}</div>
      <div className="an-slot-section-body">{children}</div>
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
  const filled = isFilled(slot);

  return (
    <div
      className={rowClass(slot, asking, filled)}
      data-testid={`slot-${name}`}
      data-source={slot.source}
      data-confidence-low={slot.source === 'memory_low_confidence' ? 'true' : undefined}
    >
      <div className="an-slot-name-v2">{label}</div>
      <div className="an-slot-value-v2">
        {filled ? <SmartValue value={slot.value} /> : <span className="an-slot-empty-mark">—</span>}
      </div>
      <div className="an-slot-src-v2">
        {filled && <SourceTag source={slot.source} />}
        {asking && <span className="an-slot-asking-tag">询问中</span>}
      </div>
    </div>
  );
}
