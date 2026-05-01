import { useState, useCallback, useRef, type KeyboardEvent } from 'react';

interface Props {
  onSend: (content: string) => void;
  onCancel?: () => void;
  disabled?: boolean;
  /** When true, shows a stop button instead of send */
  isRunning?: boolean;
}

export function InputBar({ onSend, onCancel, disabled = false, isRunning = false }: Props) {
  const [text, setText] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);

  const handleSend = useCallback(() => {
    const trimmed = text.trim();
    if (!trimmed || disabled) return;
    onSend(trimmed);
    setText('');
    // Reset textarea height
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
    }
  }, [text, disabled, onSend]);

  const handleKeyDown = useCallback(
    (e: KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        handleSend();
      }
    },
    [handleSend],
  );

  // Auto-resize textarea
  const handleInput = useCallback(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  }, []);

  return (
    <div
      data-testid="input-bar"
      className="flex items-end gap-2 p-3"
      style={{ borderTop: '1px solid var(--an-border)', background: 'var(--an-bg-raised)' }}
    >
      <textarea
        ref={textareaRef}
        data-testid="input-textarea"
        value={text}
        onChange={(e) => { setText(e.target.value); handleInput(); }}
        onKeyDown={handleKeyDown}
        disabled={disabled}
        placeholder="输入分析需求，按 Enter 发送，Shift+Enter 换行"
        rows={1}
        className="an-input max-h-40 min-h-[36px] flex-1 resize-none rounded-lg px-3 py-2 text-sm"
      />
      {isRunning ? (
        <button
          data-testid="cancel-button"
          onClick={onCancel}
          title="终止当前任务"
          className="shrink-0 rounded-lg px-4 py-2 text-sm font-medium text-white transition-colors"
          style={{ background: 'var(--an-err)' }}
        >
          终止
        </button>
      ) : (
        <button
          data-testid="send-button"
          onClick={handleSend}
          disabled={disabled || !text.trim()}
          className="shrink-0 rounded-lg px-4 py-2 text-sm font-medium text-white transition-colors disabled:cursor-not-allowed"
          style={
            disabled || !text.trim()
              ? { background: 'var(--an-bg-sunken)', color: 'var(--an-ink-4)' }
              : { background: 'var(--an-accent)' }
          }
        >
          发送
        </button>
      )}
    </div>
  );
}
