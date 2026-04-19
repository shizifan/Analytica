import { useMemo } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { EChartsViewer } from './EChartsViewer';
import type { ChatMessage as ChatMessageType } from '../types';

const PLAN_ACTION_LINE = '[确认执行] [修改方案] [重新规划]';

interface Props {
  message: ChatMessageType;
  onPlanAction?: (action: 'confirm' | 'modify' | 'regenerate') => void;
}

export function ChatMessage({ message, onPlanAction }: Props) {
  const isUser = message.role === 'user';
  const isSystem = message.role === 'system';

  // Custom markdown components: render ```echarts code blocks with EChartsViewer
  const markdownComponents = useMemo(
    () =>
      ({
        code({ children, className }: { children?: React.ReactNode; className?: string }) {
          if (/language-echarts/.test(String(className || ''))) {
            const raw = String(children).replace(/\n$/, '');
            try {
              const option = JSON.parse(raw) as Record<string, unknown>;
              return <EChartsViewer option={option} height={360} />;
            } catch {
              return <code className={String(className)}>{children}</code>;
            }
          }
          return <code className={className}>{children}</code>;
        },
        // Unwrap <pre> so EChartsViewer renders without monospace wrapper
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
        className="my-1 text-center text-xs text-gray-400"
      >
        {message.content}
      </div>
    );
  }

  // 检查消息是否包含规划操作行
  const hasPlanActions = !isUser && message.content.includes(PLAN_ACTION_LINE);
  const contentWithoutActions = hasPlanActions
    ? message.content.replace(PLAN_ACTION_LINE, '').trimEnd()
    : message.content;

  return (
    <div
      data-testid={`chat-message-${message.role}`}
      className={`my-2 flex ${isUser ? 'justify-end' : 'justify-start'}`}
    >
      <div
        className={`max-w-[75%] rounded-lg px-3 py-2 text-sm ${
          isUser
            ? 'bg-blue-600 text-white'
            : 'border border-gray-200 bg-white text-gray-800'
        }`}
      >
        {isUser ? (
          <p className="whitespace-pre-wrap">{message.content}</p>
        ) : (
          <div className="prose prose-sm max-w-none prose-p:my-1 prose-ul:my-1 prose-ol:my-1 prose-li:my-0 prose-headings:my-2 prose-pre:my-2 prose-code:text-xs">
            <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
              {contentWithoutActions}
            </ReactMarkdown>
          </div>
        )}
        {hasPlanActions && onPlanAction && (
          <div className="mt-2 flex gap-2 border-t border-gray-100 pt-2">
            <button
              type="button"
              onClick={() => onPlanAction('confirm')}
              className="rounded bg-blue-600 px-3 py-1 text-xs font-medium text-white hover:bg-blue-700"
            >
              确认执行
            </button>
            <button
              type="button"
              onClick={() => onPlanAction('modify')}
              className="rounded border border-gray-300 px-3 py-1 text-xs font-medium text-gray-600 hover:bg-gray-50"
            >
              修改方案
            </button>
            <button
              type="button"
              onClick={() => onPlanAction('regenerate')}
              className="rounded border border-gray-300 px-3 py-1 text-xs font-medium text-gray-600 hover:bg-gray-50"
            >
              重新规划
            </button>
          </div>
        )}
        {message.phase && !isUser && (
          <div className="mt-1 text-right text-[10px] text-gray-400">
            {message.phase}
          </div>
        )}
      </div>
    </div>
  );
}
