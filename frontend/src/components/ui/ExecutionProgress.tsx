import { usePlanStore } from '../../stores/planStore';

const MARK: Record<string, string> = {
  pending: '\u25CB',
  done: '\u2713',
  failed: '\u2717',
  error: '\u2717',
  skipped: '–',
};

/**
 * Phase 3.5 — execution progress bubble shown inline in the chat stream.
 * Uses the new design tokens; only renders when a plan is active.
 */
export function ExecutionProgress() {
  const plan = usePlanStore((s) => s.plan);
  const statuses = usePlanStore((s) => s.taskStatuses);
  const status = usePlanStore((s) => s.status);

  if (!plan || status === 'idle' || status === 'planning') return null;

  const total = plan.tasks.length;
  const done = plan.tasks.filter((t) => statuses[t.task_id] === 'done').length;
  const pct = total ? Math.round((done / total) * 100) : 0;

  return (
    <div className="an-msg-row assistant">
      <div className="an-role-avatar assistant">A</div>
      <div className="an-msg-bubble" style={{ flex: 1, minWidth: 0, padding: 0 }}>
        <div
          className="an-exec-progress"
          data-testid="execution-progress"
          style={{ border: 0, borderRadius: 0, background: 'transparent' }}
        >
          <div className="an-exec-head">
            <span>正在执行分析任务</span>
            <span className="an-exec-count">
              {done}/{total} · {pct}%
            </span>
          </div>
          <div className="an-exec-bar">
            <div className="fill" style={{ width: `${pct}%` }} />
          </div>
          <div className="an-exec-rows">
            {plan.tasks.map((t) => {
              const s = statuses[t.task_id] ?? 'pending';
              return (
                <div key={t.task_id} className={`an-exec-row s-${s}`}>
                  <span className="an-exec-mark">
                    {s === 'running' ? <span className="an-spinner" /> : (MARK[s] ?? '○')}
                  </span>
                  <span
                    style={{
                      flex: 1,
                      minWidth: 0,
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                    }}
                  >
                    {t.name || t.skill}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
