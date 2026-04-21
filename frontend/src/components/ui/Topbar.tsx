import { Icon } from './Icon';
import { useSessionStore } from '../../stores/sessionStore';
import { useWsStore } from '../../stores/wsStore';

const PHASE_LABELS: Record<string, string> = {
  idle: '待机',
  perception: '感知中',
  planning: '规划中',
  executing: '执行中',
  reflection: '反思中',
  done: '已完成',
};

const WS_LABELS: Record<string, string> = {
  connected: 'connected',
  connecting: 'connecting',
  disconnected: 'disconnected',
  failed: 'failed',
};

interface Props {
  onTweaks(): void;
}

export function Topbar({ onTweaks }: Props) {
  const phase = useSessionStore((s) => s.phase);
  const wsStatus = useWsStore((s) => s.status);

  return (
    <header className="an-topbar">
      <div className="an-brand">
        <span className="an-mark">A</span>
        Analytica
        <span className="an-brand-sub">/ 多维能动决策智能体</span>
      </div>
      <div className="an-meta">
        <span className={`an-pill ws-${wsStatus}`}>
          <span className="an-dot" />
          WS · {WS_LABELS[wsStatus] ?? wsStatus}
        </span>
        <span className={`an-pill phase-${phase}`}>
          <span className="an-dot" />
          {PHASE_LABELS[phase] ?? phase}
        </span>
        <a className="an-console-btn" href="/admin" title="管理控制台">
          <Icon name="grid" size={12} />
          <span>控制台</span>
        </a>
        <button
          type="button"
          className="an-icon-btn"
          title="Tweaks"
          onClick={onTweaks}
        >
          <Icon name="sliders" />
        </button>
      </div>
    </header>
  );
}
