import { useMemo } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { EChartsViewer } from '../EChartsViewer';
import type { ChatMessage as ChatMessageType } from '../../types';

const PLAN_ACTION_LINE = '[确认执行] [修改方案] [重新规划]';

interface Props {
  message: ChatMessageType;
  onPlanAction?: (action: 'confirm' | 'modify' | 'regenerate') => void;
}

/**
 * Phase 3.5 — chat bubble for the v2 workbench.
 *
 * Kept separate from v1 `ChatMessage.tsx` so the existing test suite
 * (and the legacy ChatPage) stays untouched. Shares the same
 * `data-testid` hooks so any future test can target both.
 */
export function ChatMessage({ message, onPlanAction }: Props) {
  const isUser = message.role === 'user';
  const isSystem = message.role === 'system';

  const markdownComponents = useMemo(
    () =>
      ({
        code({ children, className }: { children?: React.ReactNode; className?: string }) {
          if (/language-echarts/.test(String(className || ''))) {
            const raw = String(children).replace(/\n$/, '');
            try {
              const option = JSON.parse(raw) as Record<string, unknown>;
              return <EChartsViewer option={option} height={300} />;
            } catch {
              return <code className={String(className)}>{children}</code>;
            }
          }
          return <code className={className}>{children}</code>;
        },
        pre({ children }: { children?: React.ReactNode }) {
          return <>{children}</>;
        },
      }) as Record<string, (props: Record<string, unknown>) => React.ReactElement>,
    [],
  );

  if (isSystem) {
    return (
      <div
        data-testid="chat-message-system"
        className="an-msg-row system"
      >
        <div className="an-msg-bubble">— {message.content} —</div>
      </div>
    );
  }

  const hasPlanActions = !isUser && message.content.includes(PLAN_ACTION_LINE);
  const contentWithoutActions = hasPlanActions
    ? message.content.replace(PLAN_ACTION_LINE, '').trimEnd()
    : message.content;

  if (isUser) {
    return (
      <div data-testid="chat-message-user" className="an-msg-row user">
        <div className="an-msg-bubble">
          <div style={{ whiteSpace: 'pre-wrap' }}>{message.content}</div>
        </div>
        <div className="an-role-avatar user">U</div>
      </div>
    );
  }

  return (
    <div data-testid="chat-message-assistant" className="an-msg-row assistant">
      <div className="an-role-avatar assistant">A</div>
      <div className="an-msg-bubble" style={{ flex: 1, minWidth: 0 }}>
        <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
          {contentWithoutActions}
        </ReactMarkdown>
        {hasPlanActions && onPlanAction && (
          <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
            <button
              type="button"
              className="an-btn primary"
              onClick={() => onPlanAction('confirm')}
            >
              确认执行
            </button>
            <button
              type="button"
              className="an-btn"
              onClick={() => onPlanAction('modify')}
            >
              修改方案
            </button>
            <button
              type="button"
              className="an-btn ghost"
              onClick={() => onPlanAction('regenerate')}
            >
              重新规划
            </button>
          </div>
        )}
        {message.phase && (
          <div className="an-msg-meta">
            <span className="phase">{message.phase}</span>
          </div>
        )}
      </div>
    </div>
  );
}
