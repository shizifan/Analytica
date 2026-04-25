import { useDegradationStore } from '../../../stores/degradationStore';
import type { DegradationEvent, DegradationSeverity } from '../../../stores/degradationStore';

const SEVERITY_META: Record<DegradationSeverity, { icon: string; label: string; cls: string }> = {
  error: { icon: '❗', label: '错误', cls: 's-error' },
  warn:  { icon: '⚠️', label: '警告', cls: 's-warn' },
  info:  { icon: 'ℹ️', label: '信息', cls: 's-info' },
};

const LAYER_LABEL: Record<string, string> = {
  planning: '规划',
  execution: '执行',
  collector: '报告整合',
  parser: '配置解析',
  visualization: '可视化',
};

function layerLabel(layer: string): string {
  return LAYER_LABEL[layer] ?? layer;
}

function AffectedBlock({ data }: { data: Record<string, unknown> }) {
  const entries = Object.entries(data);
  if (entries.length === 0) return null;
  return (
    <pre className="an-trace-json-pre" style={{ marginTop: 6 }}>
      {JSON.stringify(data, null, 2)}
    </pre>
  );
}

function EventRow({ ev }: { ev: DegradationEvent }) {
  const meta = SEVERITY_META[ev.severity] ?? SEVERITY_META.info;
  return (
    <div className={`an-trace-span ${meta.cls}`}>
      <div className="an-trace-span-head" style={{ cursor: 'default' }}>
        <span className="an-trace-span-icon">{meta.icon}</span>
        <span className="an-trace-span-label">{layerLabel(ev.layer)}</span>
        <span className={`an-trace-span-status ${meta.cls}`}>{meta.label}</span>
      </div>
      <div className="an-trace-span-body">
        <div style={{ fontSize: 12, lineHeight: 1.5 }}>{ev.reason}</div>
        {ev.affected && <AffectedBlock data={ev.affected} />}
      </div>
    </div>
  );
}

export function DegradationsTab() {
  const events = useDegradationStore((s) => s.events);

  if (events.length === 0) {
    return (
      <div className="an-thinking-empty">
        无降级事件
        <br />
        <span style={{ fontSize: 10, color: 'var(--an-ink-5)' }}>
          当某些任务被过滤、报告内容被归并或图表降级渲染时，会在此显示
        </span>
      </div>
    );
  }

  // Group by severity for visual grouping; render error → warn → info.
  const order: DegradationSeverity[] = ['error', 'warn', 'info'];
  const grouped = order
    .map((sev) => ({ sev, items: events.filter((e) => e.severity === sev) }))
    .filter((g) => g.items.length > 0);

  return (
    <div className="an-trace-list">
      {grouped.map(({ sev, items }) => (
        <div key={sev} className="an-trace-group">
          <div className="an-trace-group-head" style={{ cursor: 'default' }}>
            <span className="an-trace-group-id">
              {SEVERITY_META[sev].icon} {SEVERITY_META[sev].label}
            </span>
            <span className="an-trace-group-meta">{items.length}</span>
          </div>
          <div className="an-trace-group-body">
            {items.map((ev, i) => (
              <EventRow key={`${sev}-${i}`} ev={ev} />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
