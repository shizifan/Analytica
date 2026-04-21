import { useEffect, useRef, useState } from 'react';
import { Icon } from '../Icon';
import { useSessionStore } from '../../../stores/sessionStore';
import { useSlotStore } from '../../../stores/slotStore';
import { usePlanStore } from '../../../stores/planStore';
import { useThinkingStore } from '../../../stores/thinkingStore';
import { ThinkingTab } from './ThinkingTab';
import { StatusTab } from './StatusTab';
import { PlanTab } from './PlanTab';

type TabKey = 'thinking' | 'status' | 'plan';

interface Props {
  collapsed: boolean;
  onToggle(): void;
  phaseLabel: string;
}

/**
 * Agent Inspector — Phase 3 tabbed shell.
 *
 * Three tabs mirror the agent's four phases:
 *   - 思维流: node enter/exit, tool calls, decisions (real-time stream)
 *   - 状态:   Slot fill status (perception phase)
 *   - 计划:   AnalysisPlan + live task execution progress
 */
export function AgentPane({ collapsed, onToggle, phaseLabel }: Props) {
  const [active, setActive] = useState<TabKey>('thinking');
  const userPickedRef = useRef(false);
  const phase = useSessionStore((s) => s.phase);

  const slotCount = useSlotStore((s) => Object.keys(s.slots).length);
  const filledSlotCount = useSlotStore((s) =>
    Object.values(s.slots).filter((v) => v && v.value !== null && v.value !== undefined).length,
  );
  const planTaskCount = usePlanStore((s) => s.plan?.tasks?.length ?? 0);
  const thinkingCount = useThinkingStore((s) => s.events.length);

  // Auto-focus the tab that matches the current phase — but only until
  // the user clicks a tab manually; then we stop moving the focus.
  useEffect(() => {
    if (userPickedRef.current) return;
    if (phase === 'perception') setActive('status');
    else if (phase === 'planning') setActive('plan');
    else if (phase === 'executing') setActive('plan');
    else if (phase === 'reflection' || phase === 'done') setActive('thinking');
  }, [phase]);

  const pickTab = (k: TabKey) => {
    userPickedRef.current = true;
    setActive(k);
  };

  if (collapsed) {
    return (
      <aside
        className="an-pane an-agent-pane collapsed"
        onClick={onToggle}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            onToggle();
          }
        }}
        aria-label="展开 Agent Inspector"
      >
        <span className="an-collapsed-toggle">
          <Icon name="panel-left" size={14} />
        </span>
        <span className="an-collapsed-label">
          <span className="an-pill">{phaseLabel}</span>
        </span>
        <span className="an-collapsed-spine an-mono">AGENT · INSPECTOR</span>
      </aside>
    );
  }

  return (
    <aside className="an-pane an-agent-pane">
      <div className="an-pane-header">
        <span className="an-title">Agent Inspector</span>
        <div className="an-actions">
          <button type="button" className="an-icon-btn" title="收起" onClick={onToggle}>
            <Icon name="panel-right" />
          </button>
        </div>
      </div>

      <nav className="an-tabs" role="tablist" aria-label="Agent Inspector">
        <TabButton
          active={active === 'thinking'}
          onClick={() => pickTab('thinking')}
          label="思维流"
          badge={thinkingCount}
        />
        <TabButton
          active={active === 'status'}
          onClick={() => pickTab('status')}
          label="状态"
          badge={slotCount > 0 ? `${filledSlotCount}/${slotCount}` : 0}
        />
        <TabButton
          active={active === 'plan'}
          onClick={() => pickTab('plan')}
          label="计划"
          badge={planTaskCount}
        />
      </nav>

      <div className="an-tab-body" role="tabpanel">
        {active === 'thinking' && <ThinkingTab />}
        {active === 'status' && <StatusTab />}
        {active === 'plan' && <PlanTab />}
      </div>
    </aside>
  );
}

function TabButton({
  active,
  onClick,
  label,
  badge,
}: {
  active: boolean;
  onClick(): void;
  label: string;
  badge: number | string;
}) {
  const showBadge = typeof badge === 'string' ? true : badge > 0;
  return (
    <button
      type="button"
      role="tab"
      aria-selected={active}
      className={`an-tab${active ? ' active' : ''}`}
      onClick={onClick}
    >
      {label}
      {showBadge && <span className="an-tab-badge">{badge}</span>}
    </button>
  );
}
