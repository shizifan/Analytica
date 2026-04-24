import { useState } from 'react';
import { useTraceStore } from '../../../stores/traceStore';
import type { Span } from '../../../stores/traceStore';

// ── Helpers ─────────────────────────────────────────────────────

function spanIcon(type: string) {
  if (type === 'llm_call') return '🤖';
  if (type === 'param_resolve') return '🔧';
  return '📡';
}

function spanLabel(type: string) {
  if (type === 'llm_call') return 'LLM 调用';
  if (type === 'param_resolve') return '参数解析';
  return 'API 调用';
}

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
      // look for the next same-type end
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

// ── JsonBlock ────────────────────────────────────────────────────

function JsonBlock({ label, data }: { label: string; data: Record<string, unknown> }) {
  return (
    <div className="an-trace-json-block">
      <div className="an-trace-json-label">{label}</div>
      <pre className="an-trace-json-pre">{JSON.stringify(data, null, 2)}</pre>
    </div>
  );
}

// ── DataTable ────────────────────────────────────────────────────

function DataTable({ rows }: { rows: Record<string, unknown>[] }) {
  if (!rows || rows.length === 0) return null;
  const cols = Object.keys(rows[0]);
  return (
    <div className="an-trace-table-wrap">
      <table className="an-trace-table">
        <thead>
          <tr>
            {cols.map((c) => <th key={c}>{c}</th>)}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i}>
              {cols.map((c) => (
                <td key={c}>{row[c] == null ? '—' : String(row[c])}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── OutputBlock — splits meta + data table ────────────────────────

function OutputBlock({ output }: { output: Record<string, unknown> }) {
  const { data, ...meta } = output;
  const rows = Array.isArray(data) ? (data as Record<string, unknown>[]) : null;
  const hasMeta = Object.keys(meta).length > 0;
  return (
    <>
      {hasMeta && <JsonBlock label="出参" data={meta} />}
      {rows && rows.length > 0 && (
        <div className="an-trace-json-block">
          <div className="an-trace-json-label">数据（{rows.length} 行）</div>
          <DataTable rows={rows} />
        </div>
      )}
    </>
  );
}

// ── SpanPairRow ──────────────────────────────────────────────────

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
          {start.input && <JsonBlock label="入参" data={start.input} />}
          {end?.output && <OutputBlock output={end.output} />}
        </div>
      )}
    </div>
  );
}

// ── TaskGroup ────────────────────────────────────────────────────

function TaskGroup({ taskId, spans }: { taskId: string; spans: Span[] }) {
  const [open, setOpen] = useState(true);
  const hasError = taskHasError(spans);
  const latency = latencyFromSpans(spans);
  const pairs = pairSpans(spans);

  return (
    <div className={`an-trace-group${hasError ? ' s-error' : ''}`}>
      <button type="button" className="an-trace-group-head" onClick={() => setOpen((o) => !o)}>
        <span className="an-trace-group-chevron">{open ? '▾' : '▸'}</span>
        <span className="an-trace-group-id">{taskId}</span>
        <span className="an-trace-group-meta">
          {pairs.length} 次调用
          {latency != null && <> · {latency}ms</>}
        </span>
        {hasError && <span className="an-trace-badge s-error">错误</span>}
      </button>

      {open && (
        <div className="an-trace-group-body">
          {pairs.map((p, i) => (
            <SpanPairRow key={`${p.start.span_id}-${i}`} pair={p} />
          ))}
        </div>
      )}
    </div>
  );
}

// ── TraceTab ─────────────────────────────────────────────────────

export function TraceTab() {
  const spansByTask = useTraceStore((s) => s.spansByTask);
  const entries = Object.entries(spansByTask);

  if (entries.length === 0) {
    return (
      <div className="an-thinking-empty">
        执行后自动显示调用链路
        <br />
        <span style={{ fontSize: 10, color: 'var(--an-ink-5)' }}>
          API 调用和 LLM 调用的输入输出将在此展示
        </span>
      </div>
    );
  }

  return (
    <div className="an-trace-list">
      {entries.map(([taskId, spans]) => (
        <TaskGroup key={taskId} taskId={taskId} spans={spans} />
      ))}
    </div>
  );
}
