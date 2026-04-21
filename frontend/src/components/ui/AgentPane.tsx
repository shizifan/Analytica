import type { ReactNode } from 'react';
import { Icon } from './Icon';

interface Props {
  collapsed: boolean;
  onToggle(): void;
  phaseLabel: string;
  /** Placeholder body — Phase 3 replaces with tabbed inspector. */
  children?: ReactNode;
}

export function AgentPane({ collapsed, onToggle, phaseLabel, children }: Props) {
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
          <button
            type="button"
            className="an-icon-btn"
            title="收起"
            onClick={onToggle}
          >
            <Icon name="panel-right" />
          </button>
        </div>
      </div>

      <div style={{ flex: 1, minHeight: 0, overflowY: 'auto' }}>
        {children ?? (
          <div className="an-agent-empty">
            等待对话开始...
            <br />
            <span className="an-mono" style={{ fontSize: 10, color: 'var(--an-ink-5)' }}>
              Phase 3 · 思维流 / 状态 / 计划
            </span>
          </div>
        )}
      </div>
    </aside>
  );
}
