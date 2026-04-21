import { useEffect, useRef, useState } from 'react';
import { useSessionStore } from '../../stores/sessionStore';
import { usePlanStore } from '../../stores/planStore';
import { useThinkingStore } from '../../stores/thinkingStore';
import type { AgentPhase, ThinkingEvent } from '../../types';

/**
 * Phase 3.5.2 — the waiting-state bubble shown while the agent is
 * between messages. Replaces the old "正在思考…" one-liner.
 *
 * Inputs:
 *   - `session.phase`  — drives the primary label
 *   - latest `thinkingStore.events` — drives the live subtitle
 *   - `plan.tasks + taskStatuses` — when executing, shows current task
 *   - local elapsed counter per phase, warns after 20s
 */
const PHASE_LABEL: Record<AgentPhase, string> = {
  idle: '启动中',
  perception: '理解你的需求',
  planning: '设计分析方案',
  executing: '执行分析任务',
  reflection: '整理分析洞察',
  done: '即将完成',
};

const PHASE_SUB: Record<AgentPhase, string> = {
  idle: '',
  perception: '匹配槽位 · 查询历史偏好 · 生成结构化意图',
  planning: '选择技能 · 编排任务 DAG · 估算耗时',
  executing: '并行调用技能 · 汇总中间结果',
  reflection: '提取偏好 · 识别可复用模板',
  done: '',
};

function describeEvent(evt: ThinkingEvent | undefined): { tag: string; text: string } | null {
  if (!evt || !evt.payload) return null;
  const p = evt.payload as Record<string, unknown>;

  if (evt.kind === 'phase') {
    const node = (p.node as string) ?? evt.phase ?? '';
    if (p.event === 'phase_enter') {
      return { tag: 'PHASE', text: `进入 ${node}` };
    }
    if (p.event === 'phase_exit') {
      // Exit of a node is the most informative — show a compact summary.
      const bits: string[] = [];
      if (p.slot_total !== undefined) bits.push(`槽位 ${p.slot_filled ?? 0}/${p.slot_total}`);
      if (p.task_count !== undefined) bits.push(`${p.task_count} 任务`);
      if (p.done !== undefined) bits.push(`完成 ${p.done}`);
      if (p.failed !== undefined && p.failed) bits.push(`失败 ${p.failed}`);
      return {
        tag: 'PHASE',
        text: bits.length ? `完成 ${node} · ${bits.join(' · ')}` : `完成 ${node}`,
      };
    }
  }

  if (evt.kind === 'tool') {
    const skill = (p.skill_id as string) ?? 'skill';
    if (p.event === 'tool_call_start') {
      return { tag: 'TOOL', text: `调用 ${skill}…` };
    }
    if (p.event === 'tool_call_end') {
      const preview = p.preview as Record<string, unknown> | undefined;
      const status = (p.status as string) ?? '';
      if (status === 'failed' || status === 'error') {
        return { tag: 'TOOL', text: `${skill} 失败` };
      }
      if (preview?.rows !== undefined) {
        return { tag: 'TOOL', text: `${skill} · ${preview.rows} 行 × ${preview.cols ?? '?'} 列` };
      }
      if (preview?.count !== undefined) {
        return { tag: 'TOOL', text: `${skill} · ${preview.count} 条` };
      }
      if (preview?.char_count !== undefined) {
        return { tag: 'TOOL', text: `${skill} · ${preview.char_count} 字` };
      }
      return { tag: 'TOOL', text: `${skill} 完成` };
    }
  }

  if (evt.kind === 'decision') {
    const reason = (p.reason as string) ?? (p.branch as string) ?? '决策';
    return { tag: 'DECISION', text: reason };
  }

  return null;
}

export function ThinkingIndicator() {
  const sending = useSessionStore((s) => s.sending);
  const phase = useSessionStore((s) => s.phase);
  const events = useThinkingStore((s) => s.events);

  const plan = usePlanStore((s) => s.plan);
  const taskStatuses = usePlanStore((s) => s.taskStatuses);

  const [elapsed, setElapsed] = useState(0);
  const startRef = useRef<number>(0);

  // Reset the clock when a thinking session starts (sending → true) and
  // at every phase transition within that session. Do NOT reset when
  // sending → false, otherwise the counter blinks to 0 on the very last
  // frame before the indicator unmounts.
  useEffect(() => {
    if (sending) {
      startRef.current = Date.now();
      setElapsed(0);
    }
  }, [sending, phase]);

  // Tick only while sending; cleans up on phase change or stop.
  useEffect(() => {
    if (!sending) return;
    const id = window.setInterval(() => {
      if (startRef.current === 0) return;
      setElapsed(Math.max(0, Math.round((Date.now() - startRef.current) / 1000)));
    }, 500);
    return () => window.clearInterval(id);
  }, [sending, phase]);

  if (!sending) return null;

  const primary = PHASE_LABEL[phase] ?? '思考中';
  const staticSub = PHASE_SUB[phase] ?? '';

  // During execution, prefer the currently-running task as the subtitle.
  let liveSub: { tag: string; text: string } | null = null;
  if (phase === 'executing' && plan) {
    const running = plan.tasks.find((t) => taskStatuses[t.task_id] === 'running');
    const doneCount = plan.tasks.filter((t) => taskStatuses[t.task_id] === 'done').length;
    if (running) {
      liveSub = {
        tag: 'RUN',
        text: `${doneCount + 1}/${plan.tasks.length} · ${running.name || running.skill}`,
      };
    }
  }
  if (!liveSub) {
    liveSub = describeEvent(events[events.length - 1]);
  }

  const subtitle = liveSub ?? (staticSub ? { tag: '', text: staticSub } : null);
  const isSlow = elapsed >= 20;

  return (
    <div className="an-msg-row assistant" data-testid="thinking-indicator">
      <div className="an-role-avatar assistant breathing">A</div>
      <div className="an-thinking-indicator">
        <div className="an-thinking-primary">
          <span className="an-thinking-dots" aria-hidden>
            <span />
            <span />
            <span />
          </span>
          <span>{primary}</span>
          <span className={`an-thinking-elapsed${isSlow ? ' slow' : ''}`}>
            {elapsed}s
          </span>
        </div>
        {subtitle && (
          <div className="an-thinking-subtitle">
            {subtitle.tag && <span className="kind-tag">{subtitle.tag}</span>}
            <span className="subtitle-text" title={subtitle.text}>
              {subtitle.text}
            </span>
          </div>
        )}
      </div>
    </div>
  );
}
