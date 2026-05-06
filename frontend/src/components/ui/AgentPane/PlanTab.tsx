import { useState, useMemo } from 'react';
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
 * Multi-turn: supports switching between current and archived plans.
 */
export function PlanTab() {
  const plan = usePlanStore((s) => s.plan);
  const status = usePlanStore((s) => s.status);
  const taskStatuses = usePlanStore((s) => s.taskStatuses);
  const planHistory = usePlanStore((s) => s.planHistory);
  const selectedTurnIndex = usePlanStore((s) => s.selectedTurnIndex);
  const setSelectedTurnIndex = usePlanStore((s) => s.setSelectedTurnIndex);
  const [collapsed, setCollapsed] = useState(false);

  // Merge current plan with history for chip selection
  const allPlans = useMemo(() => {
    const items: { turnIndex: number; plan: typeof plan }[] = [];
    if (planHistory.length > 0) {
      for (const hp of planHistory) {
        const ti = (hp as any).turn_index ?? 0;
        items.push({ turnIndex: ti, plan: hp });
      }
    }
    // Current plan is the latest
    if (plan) {
      const curTi = (plan as any).turn_index ?? (items.length > 0 ? items[items.length - 1].turnIndex + 1 : 0);
      items.push({ turnIndex: curTi, plan });
    } else if (items.length > 0) {
      // No current plan but we have history
      const last = items[items.length - 1];
      items.push({ turnIndex: last.turnIndex + 1, plan: last.plan });
    }
    return items;
  }, [plan, planHistory]);

  const displayPlan = useMemo(() => {
    if (selectedTurnIndex === 0 || allPlans.length <= 1) return plan;
    const match = allPlans.find((p) => p.turnIndex === selectedTurnIndex);
    return match?.plan ?? plan;
  }, [plan, selectedTurnIndex, allPlans]);

  const hasHistory = allPlans.length > 1;

  if (!displayPlan && !hasHistory) {
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

  // If no current plan but we have history, show a placeholder
  if (!displayPlan) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {hasHistory && (
          <div className="an-plan-turn-chips">
            {allPlans.map((p) => (
              <button
                key={p.turnIndex}
                type="button"
                className={`an-turn-chip ${p.turnIndex === selectedTurnIndex ? 'active' : ''}`}
                onClick={() => setSelectedTurnIndex(p.turnIndex)}
              >
                R{p.turnIndex}
              </button>
            ))}
          </div>
        )}
        <div className="an-thinking-empty">
          等待新方案生成…
        </div>
      </div>
    );
  }

  const tasks = displayPlan.tasks;
  const total = tasks.length;
  const doneCount = tasks.filter(
    (t) => taskStatuses[t.task_id] === 'done',
  ).length;
  const pct = total ? Math.round((doneCount / total) * 100) : 0;
  const isCurrent = displayPlan === plan;
  const isExecuting = (isCurrent && status === 'executing') || status === 'done';

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      {hasHistory && (
        <div className="an-plan-turn-chips">
          {allPlans.map((p) => (
            <button
              key={p.turnIndex}
              type="button"
              className={`an-turn-chip ${p.turnIndex === selectedTurnIndex ? 'active' : ''}`}
              onClick={() => setSelectedTurnIndex(p.turnIndex)}
            >
              R{p.turnIndex}
            </button>
          ))}
        </div>
      )}

      <div className="an-plan-card" data-testid="plan-task-list">
        <button
          type="button"
          className="an-plan-head"
          onClick={() => setCollapsed((c) => !c)}
          style={{ border: 0, width: '100%', cursor: 'pointer', fontFamily: 'inherit' }}
        >
          <span className="an-plan-title">
            <span style={{ letterSpacing: '0.04em' }}>分析方案</span>
            {displayPlan.version && (
              <span className="an-mono" style={{ color: 'var(--an-ink-4)' }}>
                v{displayPlan.version}
              </span>
            )}
            {!isCurrent && (
              <span style={{ fontSize: 10, color: 'var(--an-ink-5)', marginLeft: 4 }}>
                (R{(displayPlan as any).turn_index ?? '?'})
              </span>
            )}
          </span>
          <span className="an-plan-meta">
            {isExecuting ? `${doneCount}/${total} · ${pct}%` : `${total} 任务`} · {collapsed ? '▸' : '▾'}
          </span>
        </button>

        {isExecuting && isCurrent && (
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

        {!collapsed && tasks.map((task, i) => {
          const s = taskStatuses[task.task_id] ?? 'pending';
          const mark = MARK[s] ?? '?';
          return (
            <div
              key={task.task_id}
              className={statusClass(s)}
              title={`tool: ${task.tool}\ndeps: ${task.depends_on.join(', ') || 'none'}`}
            >
              <span className="an-plan-idx">
                {s === 'running' ? <span className="an-spinner" /> : mark || String(i + 1).padStart(2, '0')}
              </span>
              <div className="an-plan-body">
                <div className="an-plan-name">
                  {i + 1}. {task.name || task.tool}
                </div>
                {task.description && (
                  <div className="an-plan-desc">{task.description}</div>
                )}
              </div>
              <span className="an-plan-tool">{task.tool}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
