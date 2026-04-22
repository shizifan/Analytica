import { useMemo } from 'react';
import { TaskResultCard } from './TaskResultCard';
import { FileResultCard } from './FileResultCard';
import type { TaskResult, TaskResultsPayload } from '../../types';

interface Props {
  payload: TaskResultsPayload;
}

/**
 * Phase 3.7 — the top-level block inside an assistant bubble that hosts
 * one or more result cards. Groups related tasks so charts show up
 * alongside their upstream data as a single tabbed card.
 *
 * Grouping rule (conservative, depends_on-driven):
 *   - Chart task T with `depends_on: [D]` where D is a `data_fetch /
 *     table` task in the same payload → merge D into T's card as the
 *     "数据" tab, and drop D's standalone card.
 *   - Everything else renders as its own card in plan order.
 */
export function TaskResultsBlock({ payload }: Props) {
  const cards = useMemo(() => groupTasks(payload.tasks), [payload.tasks]);

  if (cards.length === 0) return null;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10, width: '100%' }}>
      {cards.map((c) => {
        if (c.primary.output_type === 'file') {
          return <FileResultCard key={c.primary.task_id} primary={c.primary} />;
        }
        return (
          <TaskResultCard
            key={c.primary.task_id}
            primary={c.primary}
            tableSource={c.tableSource}
          />
        );
      })}
    </div>
  );
}

interface Card {
  primary: TaskResult;
  tableSource?: TaskResult;
}

function groupTasks(tasks: TaskResult[]): Card[] {
  const byId = new Map(tasks.map((t) => [t.task_id, t]));
  const consumed = new Set<string>();

  const cards: Card[] = [];
  for (const task of tasks) {
    if (consumed.has(task.task_id)) continue;

    if (task.output_type === 'chart') {
      // Find the first upstream data_fetch / table dep in the payload.
      const upstreamId = task.depends_on.find((dep) => {
        const d = byId.get(dep);
        return !!d && d.output_type === 'table';
      });
      const upstream = upstreamId ? byId.get(upstreamId) : undefined;
      if (upstream) consumed.add(upstream.task_id);
      cards.push({ primary: task, tableSource: upstream });
    } else {
      cards.push({ primary: task });
    }
  }

  // Render in payload order; if an upstream-only standalone got consumed,
  // it's naturally skipped by the `consumed` filter above.
  return cards.filter((c) => !consumed.has(c.primary.task_id));
}
