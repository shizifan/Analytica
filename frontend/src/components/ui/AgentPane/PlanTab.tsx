import { useState } from 'react';
import { usePlanStore } from '../../../stores/planStore';

const MARK: Record<string, string> = {
  pending: '\u25CB', // ○
  running: '', // spinner element
  done: '\u2713',
  error: '\u2717',
  failed: '\u2717',
  skipped: '–',
};

function statusClass(s: string): string {
  if (s === 'done') return 'an-plan-task s-done';
  if (s === 'running') return 'an-plan-task s-running';
  if (s === 'error' || s === 'failed') return 'an-plan-task s-failed';
  if (s === 'skipped') return 'an-plan-task s-skipped';
  return 'an-plan-task';
}

/**
 * Phase 3.5 — plan + live execution redrawn with new design tokens.
 */
export function PlanTab() {
  const plan = usePlanStore((s) => s.plan);
  const status = usePlanStore((s) => s.status);
  const taskStatuses = usePlanStore((s) => s.taskStatuses);
  const [collapsed, setCollapsed] = useState(false);

  if (!plan) {
    return (
      <div className="an-thinking-empty">
        尚未生成分析方案
        <br />
        <span className="an-mono" style={{ fontSize: 10, color: 'var(--an-ink-5)' }}>
          等待 planning 完成…
        </span>
      </div>
    );
  }

  const total = plan.tasks.length;
  const doneCount = plan.tasks.filter(
    (t) => taskStatuses[t.task_id] === 'done',
  ).length;
  const pct = total ? Math.round((doneCount / total) * 100) : 0;
  const isExecuting = status === 'executing' || status === 'done';

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <div className="an-plan-card" data-testid="plan-task-list">
        <button
          type="button"
          className="an-plan-head"
          onClick={() => setCollapsed((c) => !c)}
          style={{ border: 0, width: '100%', cursor: 'pointer', fontFamily: 'inherit' }}
        >
          <span className="an-plan-title">
            <span style={{ letterSpacing: '0.04em' }}>分析方案</span>
            {plan.version && (
              <span className="an-mono" style={{ color: 'var(--an-ink-4)' }}>
                v{plan.version}
              </span>
            )}
          </span>
          <span className="an-plan-meta">
            {isExecuting ? `${doneCount}/${total} · ${pct}%` : `${total} 任务`} · {collapsed ? '▸' : '▾'}
          </span>
        </button>

        {isExecuting && (
          <div
            className="an-plan-progress"
            role="progressbar"
            aria-valuenow={pct}
            aria-valuemin={0}
            aria-valuemax={100}
            data-testid="execution-progress"
          >
            <div className="fill" style={{ width: `${pct}%` }} />
          </div>
        )}

        {!collapsed && plan.tasks.map((task, i) => {
          const s = taskStatuses[task.task_id] ?? 'pending';
          const mark = MARK[s] ?? '?';
          return (
            <div
              key={task.task_id}
              className={statusClass(s)}
              title={`skill: ${task.skill}\ndeps: ${task.depends_on.join(', ') || 'none'}`}
            >
              <span className="an-plan-idx">
                {s === 'running' ? <span className="an-spinner" /> : mark || String(i + 1).padStart(2, '0')}
              </span>
              <div className="an-plan-body">
                <div className="an-plan-name">
                  {i + 1}. {task.name || task.skill}
                </div>
                {task.description && (
                  <div className="an-plan-desc">{task.description}</div>
                )}
              </div>
              <span className="an-plan-skill">{task.skill}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
