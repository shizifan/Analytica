import { useMemo } from 'react';
import { useThinkingStore } from '../../../stores/thinkingStore';
import type { ThinkingEvent } from '../../../types';
import { SmartJSON, SmartValue } from './_primitives';

const STATUS_LABEL: Record<string, string> = {
  success: '成功',
  failed: '失败',
  error: '错误',
  partial: '部分',
  skipped: '跳过',
  running: '运行中',
};

// ── Time formatting ────────────────────────────────────────────

function formatTimestamp(evt: ThinkingEvent): { short: string; full: string } {
  // Prefer created_at (ISO from DB) when present, otherwise ts_ms.
  let date: Date | null = null;
  if (evt.created_at) {
    const d = new Date(evt.created_at);
    if (!isNaN(d.getTime())) date = d;
  }
  if (!date && evt.ts_ms) {
    // ts_ms from backend is monotonic clock, not wall time — best-effort.
    const d = new Date(evt.ts_ms);
    if (!isNaN(d.getTime()) && d.getFullYear() > 2020) date = d;
  }
  if (!date) return { short: '--:--:--', full: '' };
  const hh = String(date.getHours()).padStart(2, '0');
  const mm = String(date.getMinutes()).padStart(2, '0');
  const ss = String(date.getSeconds()).padStart(2, '0');
  const ms = String(date.getMilliseconds()).padStart(3, '0');
  return { short: `${hh}:${mm}:${ss}`, full: `${hh}:${mm}:${ss}.${ms}` };
}

// ── Inline KV (small key-value pairs in headers/summaries) ─────

function InlineKV({ pairs }: { pairs: Array<[string, unknown]> }) {
  const visible = pairs.filter(([, v]) => v !== undefined && v !== null && v !== '');
  if (visible.length === 0) return null;
  return (
    <div className="an-think-kv">
      {visible.map(([k, v]) => (
        <div key={k} className="an-think-kv-row">
          <span className="k">{k}</span>
          <SmartValue value={v} maxStringLen={80} />
        </div>
      ))}
    </div>
  );
}

// ── Row time prefix (consistent left column) ────────────────────

function TimePrefix({ evt }: { evt: ThinkingEvent }) {
  const { short, full } = formatTimestamp(evt);
  return (
    <span className="an-think-time" title={full || undefined}>
      {short}
    </span>
  );
}

// ── PHASE row ───────────────────────────────────────────────────

function PhaseRow({ evt }: { evt: ThinkingEvent }) {
  const payload = (evt.payload ?? {}) as Record<string, unknown>;
  const isExit = payload.event === 'phase_exit';
  const node = (payload.node as string) ?? evt.phase ?? '';

  // Build a compact summary line for phase_exit events.
  const pairs: Array<[string, unknown]> = [];
  if (isExit) {
    if (node === 'perception') {
      if (payload.slot_total != null)
        pairs.push(['槽位', `${payload.slot_filled ?? 0}/${payload.slot_total}`]);
      if (payload.intent_ready != null)
        pairs.push(['意图', payload.intent_ready ? '就绪' : '未完成']);
      if (payload.asking_slot) pairs.push(['追问', payload.asking_slot]);
      if (payload.clarification_round) pairs.push(['轮次', payload.clarification_round]);
    } else if (node === 'planning') {
      if (payload.task_count != null) pairs.push(['任务', payload.task_count]);
      if (payload.plan_version != null) pairs.push(['版本', `v${payload.plan_version}`]);
      if (payload.estimated_duration != null)
        pairs.push(['预估', `${payload.estimated_duration}s`]);
    } else if (node === 'execution') {
      if (payload.done != null) pairs.push(['完成', payload.done]);
      if (payload.failed != null) pairs.push(['失败', payload.failed]);
      if (payload.skipped != null) pairs.push(['跳过', payload.skipped]);
      if (payload.task_total != null) pairs.push(['总计', payload.task_total]);
      if (payload.needs_replan) pairs.push(['需重规划', '是']);
    } else if (node === 'reflection') {
      if (payload.preferences != null) pairs.push(['偏好', payload.preferences]);
      if (payload.templates != null) pairs.push(['模板', payload.templates]);
      if (payload.tool_feedback != null) pairs.push(['工具反馈', payload.tool_feedback]);
    }
  }

  return (
    <div className="an-think-row kind-phase">
      <TimePrefix evt={evt} />
      <div className="an-think-content">
        <div className="an-think-head">
          <span className="an-think-kind">PHASE · {isExit ? 'EXIT' : 'ENTER'}</span>
        </div>
        <div className="an-think-body">
          {isExit ? '完成' : '进入'} <strong>{node}</strong> 节点
        </div>
        {pairs.length > 0 && <InlineKV pairs={pairs} />}
      </div>
    </div>
  );
}

// ── TOOL row ────────────────────────────────────────────────────

function ToolRow({ evt }: { evt: ThinkingEvent }) {
  const p = (evt.payload ?? {}) as Record<string, unknown>;
  const phase = (p.event as string) ?? '';
  const tool = (p.tool_id as string) ?? '';
  const taskId = (p.task_id as string) ?? '';
  const status = (p.status as string) ?? (phase === 'tool_call_start' ? 'running' : '');
  const errorCategory = (p.error_category as string) ?? '';
  const isStart = phase === 'tool_call_start';
  const args = (p.args as Record<string, unknown>) ?? null;
  const preview = (p.preview as Record<string, unknown>) ?? null;

  // Inline summary for preview (single line).
  const previewPairs: Array<[string, unknown]> = [];
  if (preview) {
    if (preview.rows != null)
      previewPairs.push(['行/列', `${preview.rows}×${preview.cols ?? '?'}`]);
    else if (preview.count != null)
      previewPairs.push(['条数', preview.count]);
    if (Array.isArray(preview.columns))
      previewPairs.push(['字段', preview.columns]);
    else if (Array.isArray(preview.keys))
      previewPairs.push(['键', preview.keys]);
    if (preview.char_count != null)
      previewPairs.push(['字符', preview.char_count]);
    if (preview.output_type != null)
      previewPairs.push(['类型', preview.output_type]);
  }

  return (
    <div className="an-think-row kind-tool">
      <TimePrefix evt={evt} />
      <div className="an-think-content">
        <div className="an-think-head">
          <span className="an-think-kind">TOOL · {isStart ? '开始' : '结束'}</span>
          {status && (
            <span className={`an-think-status ${status}`}>
              {STATUS_LABEL[status] ?? status}
            </span>
          )}
        </div>
        <div className="an-think-body">
          <strong>{tool || 'unknown_tool'}</strong>
          {taskId && (
            <span className="an-think-tid">{taskId}</span>
          )}
        </div>

        {/* Args (start event) — collapse via SmartJSON */}
        {isStart && args && Object.keys(args).length > 0 && (
          <div className="an-think-collapsible">
            <SmartJSON data={args} initialOpen={false} label="入参" />
          </div>
        )}

        {/* Preview (end event) — inline summary, full JSON via SmartJSON */}
        {!isStart && previewPairs.length > 0 && <InlineKV pairs={previewPairs} />}

        {!isStart && errorCategory && (
          <InlineKV pairs={[['错误类型', errorCategory]]} />
        )}
      </div>
    </div>
  );
}

// ── DECISION row ────────────────────────────────────────────────

function DecisionRow({ evt }: { evt: ThinkingEvent }) {
  const p = (evt.payload ?? {}) as Record<string, unknown>;
  const branch = (p.branch as string) ?? '';
  const reason = (p.reason as string) ?? '';
  return (
    <div className="an-think-row kind-decision">
      <TimePrefix evt={evt} />
      <div className="an-think-content">
        <div className="an-think-head">
          <span className="an-think-kind">DECISION</span>
          {branch && (
            <span className="an-think-status" style={{ textTransform: 'uppercase' }}>
              {branch}
            </span>
          )}
        </div>
        <div className="an-think-body">
          {reason || branch || '决策点'}
        </div>
      </div>
    </div>
  );
}

// ── THINKING (catch-all) row ────────────────────────────────────

function ThinkingRow({ evt }: { evt: ThinkingEvent }) {
  const p = (evt.payload ?? {}) as Record<string, unknown>;
  const text = (p.text as string) ?? '';
  return (
    <div className="an-think-row kind-thinking">
      <TimePrefix evt={evt} />
      <div className="an-think-content">
        <div className="an-think-head">
          <span className="an-think-kind">THINKING</span>
        </div>
        {text ? (
          <div className="an-think-body">{text}</div>
        ) : (
          <div className="an-think-collapsible">
            <SmartJSON data={p} initialOpen={false} label="payload" />
          </div>
        )}
      </div>
    </div>
  );
}

// ── ThinkingTab ─────────────────────────────────────────────────

export function ThinkingTab() {
  const events = useThinkingStore((s) => s.events);

  // Dedupe by id, preserve insertion order.
  const ordered = useMemo(() => {
    const seen = new Set<number>();
    const out: ThinkingEvent[] = [];
    for (const e of events) {
      if (seen.has(e.id)) continue;
      seen.add(e.id);
      out.push(e);
    }
    return out;
  }, [events]);

  if (ordered.length === 0) {
    return (
      <div className="an-thinking-empty">
        等待 Agent 思考…
        <br />
        <span className="an-mono" style={{ fontSize: 10, color: 'var(--an-ink-5)' }}>
          perception / planning / execution / reflection
        </span>
      </div>
    );
  }

  return (
    <div className="an-think-list">
      {ordered.map((evt) => {
        const key = `${evt.id}_${evt.kind}`;
        if (evt.kind === 'phase') return <PhaseRow key={key} evt={evt} />;
        if (evt.kind === 'tool') return <ToolRow key={key} evt={evt} />;
        if (evt.kind === 'decision') return <DecisionRow key={key} evt={evt} />;
        return <ThinkingRow key={key} evt={evt} />;
      })}
    </div>
  );
}
