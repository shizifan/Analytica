import { usePlanStore } from '../stores/planStore';

export function ExecutionProgress() {
  const plan = usePlanStore((s) => s.plan);
  const status = usePlanStore((s) => s.status);
  const taskStatuses = usePlanStore((s) => s.taskStatuses);

  if (!plan || status !== 'executing') return null;

  const total = plan.tasks.length;
  const done = Object.values(taskStatuses).filter((s) => s === 'done').length;
  const pct = total > 0 ? Math.round((done / total) * 100) : 0;

  return (
    <div data-testid="execution-progress"
      className="my-2 rounded-lg border border-gray-200 bg-white p-3 text-xs"
    >
      <div className="mb-1 font-medium text-gray-700">
        &#9635; 正在执行分析任务 [{done}/{total}]
      </div>

      <ul className="mb-2 space-y-0.5">
        {plan.tasks.map((task) => {
          const ts = taskStatuses[task.task_id] ?? 'pending';
          const icon = ts === 'done' ? '\u2713'
            : ts === 'running' ? '\u27F3'
            : ts === 'error' ? '\u2717'
            : '\u25CB';
          const color = ts === 'done' ? 'text-green-600'
            : ts === 'running' ? 'text-blue-600 animate-pulse'
            : ts === 'error' ? 'text-red-600'
            : 'text-gray-400';

          return (
            <li key={task.task_id} className="flex items-center gap-2 pl-2">
              <span className={`font-mono ${color}`}>{icon}</span>
              <span className={ts === 'done' ? 'text-gray-600' : 'text-gray-500'}>
                {task.name || task.tool}
              </span>
              {ts === 'running' && <span className="text-blue-500">进行中...</span>}
            </li>
          );
        })}
      </ul>

      <div className="h-2 w-full overflow-hidden rounded-full bg-gray-200">
        <div
          className="h-full rounded-full bg-blue-500 transition-all duration-300"
          style={{ width: `${pct}%` }}
        />
      </div>
      <div className="mt-1 text-right text-gray-500">{pct}%</div>
    </div>
  );
}
