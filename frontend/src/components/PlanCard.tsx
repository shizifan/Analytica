import { usePlanStore } from '../stores/planStore';
import { useState } from 'react';

const STATUS_ICONS: Record<string, string> = {
  pending: '\u25CB',   // ○
  running: '\u27F3',   // ⟳
  done: '\u2713',      // ✓
  error: '\u2717',     // ✗
};

export function PlanCard() {
  const plan = usePlanStore((s) => s.plan);
  const status = usePlanStore((s) => s.status);
  const taskStatuses = usePlanStore((s) => s.taskStatuses);
  const [collapsed, setCollapsed] = useState(false);

  if (status === 'idle') return null;

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-3">
      <button
        className="mb-1 flex w-full items-center justify-between text-sm font-semibold text-gray-700"
        onClick={() => setCollapsed((c) => !c)}
      >
        <span>分析方案</span>
        <span className="text-xs text-gray-400">{collapsed ? '\u25B6' : '\u25BC'}</span>
      </button>

      {!collapsed && (
        <>
          {status === 'planning' && (
            <div className="flex items-center gap-2 text-xs text-gray-500">
              <span className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-blue-400 border-t-transparent" />
              规划方案生成中...
            </div>
          )}

          {status === 'failed' && (
            <div className="rounded bg-red-50 p-2 text-xs text-red-600">
              规划失败
              <button className="ml-2 rounded bg-red-100 px-2 py-0.5 text-red-700 hover:bg-red-200">
                重新规划
              </button>
            </div>
          )}

          {plan && (status === 'ready' || status === 'executing' || status === 'done') && (
            <div data-testid="plan-task-list" className="space-y-1">
              {plan.tasks.map((task, i) => {
                const ts = taskStatuses[task.task_id] ?? 'pending';
                const icon = STATUS_ICONS[ts] ?? '?';
                const colorClass = ts === 'done' ? 'text-green-600'
                  : ts === 'running' ? 'text-blue-600 animate-pulse'
                  : ts === 'error' ? 'text-red-600'
                  : 'text-gray-400';

                return (
                  <div key={task.task_id}
                    className="flex items-start gap-2 rounded px-2 py-1 text-xs hover:bg-gray-50"
                    title={`skill: ${task.skill}\ndepends: ${task.depends_on.join(', ') || 'none'}`}
                  >
                    <span className={`mt-0.5 font-mono ${colorClass}`}>{icon}</span>
                    <div className="min-w-0 flex-1">
                      <span className="font-medium text-gray-700">
                        {i + 1}. {task.name || task.skill}
                      </span>
                      {task.description && (
                        <p className="truncate text-gray-500">{task.description}</p>
                      )}
                    </div>
                    <span className="shrink-0 text-gray-400">{task.skill}</span>
                  </div>
                );
              })}
            </div>
          )}
        </>
      )}
    </div>
  );
}
