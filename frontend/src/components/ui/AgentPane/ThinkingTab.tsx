import { useMemo } from 'react';
import { useThinkingStore } from '../../../stores/thinkingStore';
import type { ThinkingEvent } from '../../../types';

const STATUS_LABEL: Record<string, string> = {
  success: '成功',
  failed: '失败',
  error: '错误',
  partial: '部分',
  skipped: '跳过',
  running: '运行中',
};

function formatKV(pairs: Array<[string, unknown]>): Array<[string, string]> {
  return pairs
    .filter(([, v]) => v !== undefined && v !== null && v !== '')
    .map(([k, v]) => [
      k,
      typeof v === 'object' ? JSON.stringify(v) : String(v),
    ]);
}

function PhaseRow({ evt }: { evt: ThinkingEvent }) {
  const payload = (evt.payload ?? {}) as Record<string, unknown>;
  const eventName = payload.event === 'phase_exit' ? '完成' : '进入';
  const node = (payload.node as string) ?? evt.phase ?? '';

  // Build an optional summary line for phase_exit events.
  const kv: Array<[string, string]> = [];
  const pushIf = (k: string, v: unknown, formatter?: (x: unknown) => string) => {
    if (v === undefined || v === null || v === '') return;
    kv.push([k, formatter ? formatter(v) : String(v)]);
  };
  if (payload.event === 'phase_exit') {
    if (node === 'perception') {
      pushIf('槽位', payload.slot_total, (v) => `${payload.slot_filled ?? 0}/${v}`);
      pushIf('意图', payload.intent_ready, (v) => (v ? '就绪' : '未完成'));
      pushIf('追问', payload.asking_slot);
      if (payload.clarification_round) pushIf('轮次', payload.clarification_round);
    } else if (node === 'planning') {
      pushIf('任务', payload.task_count);
      pushIf('版本', payload.plan_version, (v) => `v${v}`);
      pushIf('预估', payload.estimated_duration, (v) => `${v}s`);
    } else if (node === 'execution') {
      pushIf('完成', payload.done);
      pushIf('失败', payload.failed);
      pushIf('跳过', payload.skipped);
      pushIf('总计', payload.task_total);
      if (payload.needs_replan) pushIf('需重规划', '是');
    } else if (node === 'reflection') {
      pushIf('偏好', payload.preferences);
      pushIf('模板', payload.templates);
      pushIf('技能反馈', payload.skill_feedback);
    }
  }

  return (
    <div className="an-think-row kind-phase">
      <div className="an-think-head">
        <span className="an-think-kind">
          PHASE · {eventName === '完成' ? 'EXIT' : 'ENTER'}
        </span>
        <span>#{Math.abs(evt.id)}</span>
      </div>
      <div className="an-think-body">
        {eventName === '进入' ? '进入' : '完成'} <strong>{node}</strong> 节点
      </div>
      {kv.length > 0 && (
        <div className="an-think-kv">
          {kv.map(([k, v]) => (
            <FragmentKV key={k} k={k} v={v} />
          ))}
        </div>
      )}
    </div>
  );
}

function ToolRow({ evt }: { evt: ThinkingEvent }) {
  const p = (evt.payload ?? {}) as Record<string, unknown>;
  const phase = (p.event as string) ?? '';
  const skill = (p.skill_id as string) ?? '';
  const taskId = (p.task_id as string) ?? '';
  const status = (p.status as string) ?? (phase === 'tool_call_start' ? 'running' : '');
  const errorCategory = (p.error_category as string) ?? '';
  const isStart = phase === 'tool_call_start';
  const args = (p.args as Record<string, unknown>) ?? null;
  const argEntries = args ? formatKV(Object.entries(args)) : [];
  const preview = (p.preview as Record<string, unknown>) ?? null;

  return (
    <div className="an-think-row kind-tool">
      <div className="an-think-head">
        <span className="an-think-kind">TOOL · {isStart ? '开始' : '结束'}</span>
        {status && (
          <span className={`an-think-status ${status}`}>
            {STATUS_LABEL[status] ?? status}
          </span>
        )}
      </div>
      <div className="an-think-body">
        <strong>{skill || 'unknown_skill'}</strong>
        {taskId && (
          <span className="an-mono" style={{ marginLeft: 6, color: 'var(--an-ink-4)', fontSize: 10 }}>
            {taskId}
          </span>
        )}
      </div>
      {isStart && argEntries.length > 0 && (
        <div className="an-think-kv">
          {argEntries.slice(0, 5).map(([k, v]) => (
            <FragmentKV key={k} k={k} v={v} />
          ))}
        </div>
      )}
      {!isStart && preview && (
        <div className="an-think-kv">
          {preview.rows !== undefined && (
            <FragmentKV k="行/列" v={`${preview.rows}×${preview.cols ?? '?'}`} />
          )}
          {preview.count !== undefined && preview.rows === undefined && (
            <FragmentKV k="条数" v={String(preview.count)} />
          )}
          {preview.columns !== undefined && Array.isArray(preview.columns) && (
            <FragmentKV k="字段" v={(preview.columns as string[]).join(', ')} />
          )}
          {preview.keys !== undefined && Array.isArray(preview.keys) && (
            <FragmentKV k="键" v={(preview.keys as string[]).join(', ')} />
          )}
          {preview.char_count !== undefined && (
            <FragmentKV k="字符" v={String(preview.char_count)} />
          )}
          {preview.output_type !== undefined && preview.output_type !== null && (
            <FragmentKV k="类型" v={String(preview.output_type)} />
          )}
        </div>
      )}
      {!isStart && errorCategory && (
        <div className="an-think-kv">
          <FragmentKV k="错误类型" v={errorCategory} />
        </div>
      )}
    </div>
  );
}

function FragmentKV({ k, v }: { k: string; v: string }) {
  return (
    <>
      <span className="k">{k}</span>
      <span className="v" title={v}>
        {v.length > 60 ? `${v.slice(0, 60)}…` : v}
      </span>
    </>
  );
}

function DecisionRow({ evt }: { evt: ThinkingEvent }) {
  const p = (evt.payload ?? {}) as Record<string, unknown>;
  const branch = (p.branch as string) ?? '';
  return (
    <div className="an-think-row kind-decision">
      <div className="an-think-head">
        <span className="an-think-kind">DECISION</span>
        {branch && (
          <span className="an-think-status" style={{ textTransform: 'uppercase' }}>
            {branch}
          </span>
        )}
      </div>
      <div className="an-think-body">
        {(p.reason as string) ?? branch ?? '决策点'}
      </div>
    </div>
  );
}

function ThinkingRow({ evt }: { evt: ThinkingEvent }) {
  const p = (evt.payload ?? {}) as Record<string, unknown>;
  return (
    <div className="an-think-row kind-thinking">
      <div className="an-think-head">
        <span className="an-think-kind">THINKING</span>
        <span>#{Math.abs(evt.id)}</span>
      </div>
      <div className="an-think-body">{(p.text as string) ?? JSON.stringify(p)}</div>
    </div>
  );
}

export function ThinkingTab() {
  const events = useThinkingStore((s) => s.events);

  // Dedupe by id, keep insertion order (WS + replay may overlap).
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
    <div>
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
