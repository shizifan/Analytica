import { useEffect, useRef, useState, useCallback } from 'react';
import { useSessionStore } from './stores/sessionStore';
import { useWsStore } from './stores/wsStore';
import { usePlanStore } from './stores/planStore';
import { useWebSocket } from './hooks/useWebSocket';
import { api } from './api/client';

import { SlotStatusCard } from './components/SlotStatusCard';
import { PlanCard } from './components/PlanCard';
import { ChatMessage } from './components/ChatMessage';
import { ExecutionProgress } from './components/ExecutionProgress';
import { ReflectionCard } from './components/ReflectionCard';
import { InputBar } from './components/InputBar';

import type { ReflectionSummary } from './types';

function App() {
  const sessionId = useSessionStore((s) => s.sessionId);
  const userId = useSessionStore((s) => s.userId);
  const setSession = useSessionStore((s) => s.setSession);
  const messages = useSessionStore((s) => s.messages);
  const sending = useSessionStore((s) => s.sending);
  const phase = useSessionStore((s) => s.phase);

  const wsStatus = useWsStore((s) => s.status);
  const reconnectCount = useWsStore((s) => s.reconnectCount);

  const planStatus = usePlanStore((s) => s.status);

  const { sendMessage, reconnect, onReflectionRef } = useWebSocket(sessionId);

  const [reflectionSummary, setReflectionSummary] = useState<ReflectionSummary | null>(null);
  const messagesEndRef = useRef<HTMLDivElement | null>(null);

  // Bind reflection callback
  useEffect(() => {
    onReflectionRef.current = (s: ReflectionSummary) => setReflectionSummary(s);
  }, [onReflectionRef]);

  // Auto-scroll to bottom when messages change
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, planStatus, reflectionSummary]);

  // Create session on mount if none exists
  useEffect(() => {
    if (sessionId) return;
    api.createSession('anonymous').then(({ session_id }) => {
      setSession(session_id, 'anonymous');
    }).catch(() => {
      // Session creation failed — user can retry
    });
  }, [sessionId, setSession]);

  const handleSend = useCallback(
    (content: string) => {
      sendMessage(content, userId);
    },
    [sendMessage, userId],
  );

  const handlePlanAction = useCallback(
    (action: 'confirm' | 'modify' | 'regenerate') => {
      if (!sessionId || wsStatus !== 'connected') return;
      const actionMessages: Record<string, string> = {
        confirm: '确认执行',
        modify: '修改方案',
        regenerate: '重新规划',
      };
      handleSend(actionMessages[action]);
    },
    [sessionId, wsStatus, handleSend],
  );

  // Phase label for header
  const phaseLabel: Record<string, string> = {
    idle: '等待输入',
    perception: '感知中',
    planning: '规划中',
    executing: '执行中',
    reflection: '反思中',
    done: '已完成',
  };

  return (
    <div className="flex h-screen flex-col bg-gray-50 text-gray-800">
      {/* ===== Header ===== */}
      <header className="flex h-12 shrink-0 items-center justify-between border-b border-gray-200 bg-white px-4">
        <h1 className="text-sm font-bold text-gray-800">
          Analytica &middot; 港口市场商务智能分析
        </h1>
        <div className="flex items-center gap-3 text-xs text-gray-500">
          <span className={`rounded px-2 py-0.5 ${
            phase === 'executing' ? 'bg-blue-100 text-blue-700'
            : phase === 'reflection' ? 'bg-purple-100 text-purple-700'
            : phase === 'done' ? 'bg-green-100 text-green-700'
            : 'bg-gray-100 text-gray-600'
          }`}>
            {phaseLabel[phase] ?? phase}
          </span>
          <span className={`h-2 w-2 rounded-full ${
            wsStatus === 'connected' ? 'bg-green-500'
            : wsStatus === 'connecting' ? 'animate-pulse bg-yellow-400'
            : 'bg-red-500'
          }`} title={`WebSocket: ${wsStatus}`} />
        </div>
      </header>

      {/* ===== WS disconnection banner ===== */}
      {wsStatus === 'disconnected' && (
        <div className="flex items-center justify-center gap-2 bg-red-500 px-3 py-1 text-xs text-white">
          连接已断开，正在重连... (第 {reconnectCount} 次)
        </div>
      )}
      {wsStatus === 'failed' && (
        <div className="flex items-center justify-center gap-2 bg-red-600 px-3 py-1 text-xs text-white">
          连接失败，已达最大重试次数
          <button onClick={reconnect} className="rounded bg-white/20 px-2 py-0.5 hover:bg-white/30">
            手动重连
          </button>
        </div>
      )}

      {/* ===== Main body: Left panel + Chat area ===== */}
      <div className="flex min-h-0 flex-1">
        {/* Left panel (300px) */}
        <aside className="flex w-[300px] shrink-0 flex-col gap-3 overflow-y-auto border-r border-gray-200 bg-white p-3">
          <SlotStatusCard />
          <PlanCard />
        </aside>

        {/* Main content area */}
        <main className="flex min-w-0 flex-1 flex-col">
          {/* Chat messages */}
          <div className="flex-1 overflow-y-auto px-4 py-3">
            {messages.length === 0 && (
              <div className="flex h-full items-center justify-center">
                <div className="flex flex-col items-center gap-6">
                  {/* Title */}
                  <div className="text-center">
                    <h2 className="bg-gradient-to-r from-blue-600 to-indigo-600 bg-clip-text text-2xl font-bold text-transparent">
                      多维能动决策智能体
                    </h2>
                    <p className="mt-2 text-sm text-gray-400">我是你的专属数据分析师</p>
                  </div>

                  {/* Example questions */}
                  <div className="flex flex-col items-center gap-3">
                    <div className="flex items-center gap-1.5 text-xs text-gray-400">
                      <svg className="h-4 w-4 text-amber-400" viewBox="0 0 24 24" fill="currentColor">
                        <path d="M12 2L9.19 8.63L2 9.24l5.46 4.73L5.82 21 12 17.27 18.18 21l-1.64-7.03L22 9.24l-7.19-.61L12 2z" />
                      </svg>
                      <span>试着问</span>
                    </div>
                    <button
                      type="button"
                      onClick={() => handleSend('2026年1-4月吞吐量，以图文形式返回，不需要归因')}
                      disabled={!sessionId || wsStatus !== 'connected'}
                      className="rounded-lg border border-gray-200 bg-white px-4 py-3 text-left text-sm text-gray-600 shadow-sm transition hover:border-blue-300 hover:shadow-md disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      2026年1-4月吞吐量，以图文形式返回，不需要归因
                    </button>
                  </div>
                </div>
              </div>
            )}

            {messages.map((msg) => {
              if (msg.type === 'reflection_card') {
                return (
                  <ReflectionCard
                    key={msg.id}
                    summary={reflectionSummary}
                    sessionId={sessionId ?? ''}
                  />
                );
              }
              if (msg.type === 'execution_progress') {
                return <ExecutionProgress key={msg.id} />;
              }
              return <ChatMessage key={msg.id} message={msg} onPlanAction={handlePlanAction} />;
            })}

            {/* Inline execution progress when executing */}
            {planStatus === 'executing' && <ExecutionProgress />}

            {/* Typing indicator when sending */}
            {sending && (
              <div className="my-2 flex justify-start">
                <div className="rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm text-gray-500">
                  <span className="inline-flex gap-1">
                    <span className="animate-bounce">.</span>
                    <span className="animate-bounce [animation-delay:0.1s]">.</span>
                    <span className="animate-bounce [animation-delay:0.2s]">.</span>
                  </span>
                </div>
              </div>
            )}

            <div ref={messagesEndRef} />
          </div>

          {/* Input bar */}
          <InputBar
            onSend={handleSend}
            disabled={!sessionId || wsStatus !== 'connected'}
          />
        </main>
      </div>
    </div>
  );
}

export default App;
