import { useMemo, useState } from 'react';
import { useTraceStore } from '../../../stores/traceStore';
import type { Span } from '../../../stores/traceStore';
import { useDegradationStore } from '../../../stores/degradationStore';
import type { DegradationEvent } from '../../../stores/degradationStore';
import { SmartJSON, CollapsibleSection } from './_primitives';

// ── Helpers ─────────────────────────────────────────────────────

const SPAN_META: Record<string, { icon: string; label: string }> = {
  llm_call:      { icon: '🤖', label: 'LLM 调用' },
  api_call:      { icon: '📡', label: 'API 调用' },
  param_resolve: { icon: '🔧', label: '参数解析' },
};

function spanIcon(t: string)  { return SPAN_META[t]?.icon  ?? '❓'; }
function spanLabel(t: string) { return SPAN_META[t]?.label ?? t; }

function latencyFromSpans(spans: Span[]): number | null {
  const end = spans.findLast((s) => s.status !== 'start');
  return end?.output?.latency_ms != null ? (end.output.latency_ms as number) : null;
}

function taskHasError(spans: Span[]) {
  return spans.some((s) => s.status === 'error');
}

/** Collect start+end pairs into unified call records for cleaner display. */
function pairSpans(spans: Span[]): Array<{ start: Span; end?: Span }> {
  const pairs: Array<{ start: Span; end?: Span }> = [];
  const used = new Set<number>();
  for (let i = 0; i < spans.length; i++) {
    if (used.has(i)) continue;
    const s = spans[i];
    if (s.status === 'start') {
      const j = spans.findIndex(
        (e, idx) => idx > i && !used.has(idx) && e.span_type === s.span_type && e.status !== 'start',
      );
      if (j >= 0) {
        pairs.push({ start: s, end: spans[j] });
        used.add(i);
        used.add(j);
      } else {
        pairs.push({ start: s });
        used.add(i);
      }
    } else if (!used.has(i)) {
      pairs.push({ start: s });
      used.add(i);
    }
  }
  return pairs;
}

// ── Filter chips ────────────────────────────────────────────────

type FilterKey = 'all' | 'api_call' | 'llm_call' | 'param_resolve' | 'degradation';

const FILTER_OPTIONS: Array<{ key: FilterKey; label: string }> = [
  { key: 'all',           label: '全部' },
  { key: 'api_call',      label: 'API' },
  { key: 'llm_call',      label: 'LLM' },
  { key: 'param_resolve', label: '参数解析' },
  { key: 'degradation',   label: '降级' },
];

function FilterChips({
  active,
  onChange,
  counts,
}: {
  active: FilterKey;
  onChange: (k: FilterKey) => void;
  counts: Record<FilterKey, number>;
}) {
  return (
    <div className="an-trace-filter">
      {FILTER_OPTIONS.map((opt) => (
        <button
          key={opt.key}
          type="button"
          className={`an-trace-chip${active === opt.key ? ' is-active' : ''}`}
          onClick={() => onChange(opt.key)}
        >
          {opt.label}
          <span className="an-trace-chip-count">{counts[opt.key] ?? 0}</span>
        </button>
      ))}
    </div>
  );
}

// ── SpanPairRow ─────────────────────────────────────────────────

function SpanPairRow({ pair }: { pair: { start: Span; end?: Span } }) {
  const [open, setOpen] = useState(false);
  const { start, end } = pair;
  const isError = end?.status === 'error' || start.status === 'error';
  const latency = end?.output?.latency_ms != null ? (end.output.latency_ms as number) : null;
  const isPending = !end;

  return (
    <div className={`an-trace-span${isError ? ' s-error' : ''}${isPending ? ' s-pending' : ''}`}>
      <button
        type="button"
        className="an-trace-span-head"
        onClick={() => setOpen((o) => !o)}
      >
        <span className="an-trace-span-icon">{spanIcon(start.span_type)}</span>
        <span className="an-trace-span-label">{spanLabel(start.span_type)}</span>
        {latency != null && (
          <span className="an-trace-span-latency">{latency}ms</span>
        )}
        <span className={`an-trace-span-status s-${isError ? 'error' : isPending ? 'pending' : 'ok'}`}>
          {isError ? '错误' : isPending ? '…' : '成功'}
        </span>
        <span className="an-trace-span-chevron">{open ? '▾' : '▸'}</span>
      </button>

      {open && (
        <div className="an-trace-span-body">
          {start.input && (
            <SmartJSON data={start.input} initialOpen={false} label="入参" />
          )}
          {end?.output && (
            <SmartJSON data={end.output as Record<string, unknown>} initialOpen={false} label="出参" />
          )}
        </div>
      )}
    </div>
  );
}

// ── Degradation rendering (inline next to tasks) ────────────────

const SEV_META: Record<string, { icon: string; label: string; cls: string }> = {
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

function DegradationRow({ ev }: { ev: DegradationEvent }) {
  const meta = SEV_META[ev.severity] ?? SEV_META.info;
  return (
    <div className={`an-trace-span an-trace-deg ${meta.cls}`}>
      <CollapsibleSection
        summary={
          <>
            <span className="an-trace-span-icon">{meta.icon}</span>
            <span className="an-trace-span-label">
              [{LAYER_LABEL[ev.layer] ?? ev.layer}] {meta.label}
            </span>
            <span className="an-trace-deg-reason">{ev.reason}</span>
          </>
        }
      >
        {ev.affected && Object.keys(ev.affected).length > 0 ? (
          <SmartJSON data={ev.affected} initialOpen />
        ) : (
          <span className="an-trace-deg-empty">（无 affected 详情）</span>
        )}
      </CollapsibleSection>
    </div>
  );
}

// ── TaskGroup ───────────────────────────────────────────────────

function TaskGroup({
  taskId,
  spans,
  degradations,
  filter,
}: {
  taskId: string;
  spans: Span[];
  degradations: DegradationEvent[];
  filter: FilterKey;
}) {
  const [open, setOpen] = useState(true);
  const hasError = taskHasError(spans);
  const latency = latencyFromSpans(spans);
  const allPairs = useMemo(() => pairSpans(spans), [spans]);

  const visiblePairs = useMemo(() => {
    if (filter === 'all' || filter === 'degradation') return allPairs;
    return allPairs.filter((p) => p.start.span_type === filter);
  }, [allPairs, filter]);

  const visibleDegs = filter === 'all' || filter === 'degradation' ? degradations : [];

  // Hide group entirely if filter would leave it empty.
  if (visiblePairs.length === 0 && visibleDegs.length === 0) return null;

  // Prefer the human-readable task_name from the first span; fall back to
  // task_id so legacy spans (no task_name field) still render their group
  // header. When both are present, show "T001 · 拉取吞吐量".
  const taskName = spans.find((s) => s.task_name)?.task_name;
  const headerLabel = taskName
    ? `${taskId} · ${taskName}`
    : taskId;

  return (
    <div className={`an-trace-group${hasError ? ' s-error' : ''}`}>
      <button type="button" className="an-trace-group-head" onClick={() => setOpen((o) => !o)}>
        <span className="an-trace-group-chevron">{open ? '▾' : '▸'}</span>
        <span className="an-trace-group-id" title={taskId}>{headerLabel}</span>
        <span className="an-trace-group-meta">
          {allPairs.length} 次调用
          {latency != null && <> · {latency}ms</>}
        </span>
        {degradations.length > 0 && (
          <span className="an-trace-badge s-warn" title={`${degradations.length} 个降级事件`}>
            ⚠️ {degradations.length}
          </span>
        )}
        {hasError && <span className="an-trace-badge s-error">错误</span>}
      </button>

      {open && (
        <div className="an-trace-group-body">
          {visiblePairs.map((p, i) => (
            <SpanPairRow key={`${p.start.span_id}-${i}`} pair={p} />
          ))}
          {visibleDegs.map((ev, i) => (
            <DegradationRow key={`deg-${i}`} ev={ev} />
          ))}
        </div>
      )}
    </div>
  );
}

// ── Global degradation group (events without task_id) ───────────

function GlobalDegradationGroup({ events }: { events: DegradationEvent[] }) {
  const [open, setOpen] = useState(true);
  if (events.length === 0) return null;
  const hasError = events.some((e) => e.severity === 'error');
  return (
    <div className={`an-trace-group an-trace-group-global${hasError ? ' s-error' : ''}`}>
      <button type="button" className="an-trace-group-head" onClick={() => setOpen((o) => !o)}>
        <span className="an-trace-group-chevron">{open ? '▾' : '▸'}</span>
        <span className="an-trace-group-id">⚠️ 全局降级</span>
        <span className="an-trace-group-meta">{events.length} 个事件</span>
      </button>
      {open && (
        <div className="an-trace-group-body">
          {events.map((ev, i) => (
            <DegradationRow key={`gdeg-${i}`} ev={ev} />
          ))}
        </div>
      )}
    </div>
  );
}

// ── Helpers: split degradations by task_id ──────────────────────

function splitDegradations(events: DegradationEvent[]): {
  byTask: Record<string, DegradationEvent[]>;
  global: DegradationEvent[];
} {
  const byTask: Record<string, DegradationEvent[]> = {};
  const global: DegradationEvent[] = [];
  for (const ev of events) {
    const tid = ev.affected?.task_id;
    if (typeof tid === 'string' && tid) {
      (byTask[tid] ||= []).push(ev);
    } else {
      global.push(ev);
    }
  }
  return { byTask, global };
}

// ── TraceTab ────────────────────────────────────────────────────

export function TraceTab() {
  const spansByTask = useTraceStore((s) => s.spansByTask);
  const allDegradations = useDegradationStore((s) => s.events);
  const [filter, setFilter] = useState<FilterKey>('all');

  const taskEntries = useMemo(() => Object.entries(spansByTask), [spansByTask]);
  const { byTask: degByTask, global: globalDegs } = useMemo(
    () => splitDegradations(allDegradations),
    [allDegradations],
  );

  const counts: Record<FilterKey, number> = useMemo(() => {
    let api = 0, llm = 0, pr = 0;
    for (const spans of Object.values(spansByTask)) {
      for (const p of pairSpans(spans)) {
        if (p.start.span_type === 'api_call') api++;
        else if (p.start.span_type === 'llm_call') llm++;
        else if (p.start.span_type === 'param_resolve') pr++;
      }
    }
    const deg = allDegradations.length;
    return {
      all: api + llm + pr + deg,
      api_call: api,
      llm_call: llm,
      param_resolve: pr,
      degradation: deg,
    };
  }, [spansByTask, allDegradations]);

  if (taskEntries.length === 0 && allDegradations.length === 0) {
    return (
      <div className="an-thinking-empty">
        执行后自动显示调用链路与降级事件
        <br />
        <span style={{ fontSize: 10, color: 'var(--an-ink-5)' }}>
          API 调用、LLM 调用、参数解析、降级事件全部在此呈现
        </span>
      </div>
    );
  }

  // When filter === 'degradation', hide spans entirely (only show deg).
  const showSpans = filter !== 'degradation';
  const showGlobal = filter === 'all' || filter === 'degradation';

  return (
    <div className="an-trace-list">
      <FilterChips active={filter} onChange={setFilter} counts={counts} />

      {showGlobal && <GlobalDegradationGroup events={globalDegs} />}

      {showSpans && taskEntries.map(([taskId, spans]) => (
        <TaskGroup
          key={taskId}
          taskId={taskId}
          spans={spans}
          degradations={degByTask[taskId] ?? []}
          filter={filter}
        />
      ))}

      {/* When filter === degradation: also list per-task degs flatly */}
      {filter === 'degradation' && Object.entries(degByTask).map(([taskId, evs]) => (
        <div key={`dt-${taskId}`} className="an-trace-group">
          <div className="an-trace-group-head" style={{ cursor: 'default' }}>
            <span className="an-trace-group-id">{taskId}</span>
            <span className="an-trace-group-meta">{evs.length} 个降级</span>
          </div>
          <div className="an-trace-group-body">
            {evs.map((ev, i) => <DegradationRow key={`tdeg-${i}`} ev={ev} />)}
          </div>
        </div>
      ))}
    </div>
  );
}
