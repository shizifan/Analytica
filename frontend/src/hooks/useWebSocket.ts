import { useEffect, useRef, useCallback } from 'react';
import { useWsStore } from '../stores/wsStore';
import { useSlotStore } from '../stores/slotStore';
import { usePlanStore } from '../stores/planStore';
import { useSessionStore, makeMessageId } from '../stores/sessionStore';
import { useThinkingStore, ephemeralThinkingId } from '../stores/thinkingStore';
import type { ReflectionSummary, ThinkingKind } from '../types';

const MAX_RETRIES = 10;
const MAX_BACKOFF_MS = 30_000;

function backoffMs(attempt: number): number {
  return Math.min(1000 * 2 ** attempt, MAX_BACKOFF_MS);
}

export function useWebSocket(sessionId: string | null) {
  const wsRef = useRef<WebSocket | null>(null);
  const retryRef = useRef(0);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const unmountedRef = useRef(false);

  const setConnected = useWsStore((s) => s.setConnected);
  const setWsStatus = useWsStore((s) => s.setStatus);
  const incrementReconnect = useWsStore((s) => s.incrementReconnect);

  const setSlots = useSlotStore((s) => s.setSlots);
  const setCurrentAsking = useSlotStore((s) => s.setCurrentAsking);

  const setPlan = usePlanStore((s) => s.setPlan);
  const setPlanStatus = usePlanStore((s) => s.setStatus);
  const updateTaskStatus = usePlanStore((s) => s.updateTaskStatus);

  const addMessage = useSessionStore((s) => s.addMessage);
  const setPhase = useSessionStore((s) => s.setPhase);
  const setSending = useSessionStore((s) => s.setSending);

  const appendThinking = useThinkingStore((s) => s.appendEvent);

  // Mutable ref for reflection callback
  const onReflectionRef = useRef<((s: ReflectionSummary) => void) | null>(null);

  const connect = useCallback(() => {
    if (!sessionId || unmountedRef.current) return;

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const url = `${protocol}//${window.location.host}/ws/chat/${sessionId}`;

    setWsStatus('connecting');
    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      retryRef.current = 0;
      setConnected(true);
    };

    ws.onmessage = (evt) => {
      let data: Record<string, unknown>;
      try { data = JSON.parse(evt.data); } catch { return; }

      const eventType = (data.event ?? data.type) as string;

      switch (eventType) {
        case 'connected':
          // NOTE: do NOT set maxMessageId here.
          //
          // On session switch the store is cleared first (maxMessageId=0),
          // then the WS reconnects and this event fires — if we set
          // maxMessageId = last_message_id NOW, hydrateSession (triggered by
          // the sessionId change) would read sinceId=last_message_id and
          // fetch 0 messages, leaving the chat panel empty.
          //
          // hydrateSession runs from sinceId=0 and advances maxMessageId
          // itself via addMessage(msg, dbId).  On reconnect to the *same*
          // session (no clearConversation, no re-hydration) the store already
          // holds the correct maxMessageId and needs no external seed.
          break;

        case 'slot_update':
          setSlots(data.slots as Record<string, never>);
          setCurrentAsking((data.current_asking as string) ?? null);
          setPhase('perception');
          break;

        case 'message': {
          // T3: use DB id as the stable message identity for deduplication.
          // If message_id is provided and <= maxMessageId, addMessage will
          // silently drop it (already rendered via hydration or prior event).
          const dbId = typeof data.message_id === 'number' ? data.message_id : undefined;
          addMessage(
            {
              id: dbId !== undefined ? `db_${dbId}` : makeMessageId(),
              role: 'assistant',
              content: (data.content as string) ?? '',
              phase: data.phase as string,
              type: data.type as never,
              payload: (data.payload as Record<string, unknown> | undefined) ?? null,
              timestamp: Date.now(),
            },
            dbId,
          );
          if (data.phase) setPhase(data.phase as never);
          break;
        }

        case 'intent_ready':
          setPhase('planning');
          break;

        case 'plan_update':
          setPlan(data.plan as never);
          setPlanStatus('ready');
          setPhase('planning');
          break;

        case 'task_update':
          updateTaskStatus(data.task_id as string, data.status as never);
          setPlanStatus('executing');
          setPhase('executing');
          break;

        case 'reflection':
          setPhase('reflection');
          onReflectionRef.current?.(data.summary as ReflectionSummary);
          addMessage({
            id: makeMessageId(),
            role: 'assistant',
            content: '',
            type: 'reflection_card',
            phase: 'reflection',
            timestamp: Date.now(),
          });
          break;

        case 'turn_complete':
          setSending(false);
          break;

        case 'already_running':
          // T1: another window is running for this session.
          // Inform the user and clear the "sending" spinner.
          addMessage({
            id: makeMessageId(),
            role: 'system',
            content: (data.message as string) ?? '分析正在进行中，请稍候',
            timestamp: Date.now(),
          });
          setSending(false);
          break;

        case 'error':
          addMessage({
            id: makeMessageId(),
            role: 'system',
            content: `Error: ${data.message ?? 'unknown'}`,
            timestamp: Date.now(),
          });
          setSending(false);
          break;

        case 'pong':
          break;

        // ── Phase 2 events ──────────────────────────────
        case 'thinking_stream':
          appendThinking({
            id: ephemeralThinkingId(),
            kind: ((data.kind as string) ?? 'thinking') as ThinkingKind,
            phase: (data.phase as string) ?? null,
            ts_ms: Date.now(),
            payload: (data.payload as Record<string, unknown>) ?? null,
          });
          break;

        case 'tool_call_start':
        case 'tool_call_end':
          appendThinking({
            id: ephemeralThinkingId(),
            kind: 'tool',
            phase: 'execution',
            ts_ms: Date.now(),
            payload: data as Record<string, unknown>,
          });
          break;
      }
    };

    ws.onclose = () => {
      if (unmountedRef.current) return;
      setConnected(false);

      if (retryRef.current < MAX_RETRIES) {
        const delay = backoffMs(retryRef.current);
        retryRef.current += 1;
        incrementReconnect();
        timerRef.current = setTimeout(connect, delay);
      } else {
        setWsStatus('failed');
      }
    };

    ws.onerror = () => {
      ws.close();
    };
  }, [sessionId, setConnected, setWsStatus, incrementReconnect, setSlots, setCurrentAsking, setPlan, setPlanStatus, updateTaskStatus, addMessage, setPhase, setSending, appendThinking]);

  useEffect(() => {
    unmountedRef.current = false;
    connect();
    return () => {
      unmountedRef.current = true;
      if (timerRef.current) clearTimeout(timerRef.current);
      wsRef.current?.close();
    };
  }, [connect]);

  const sendMessage = useCallback(
    (content: string, userId = 'anonymous') => {
      const ws = wsRef.current;
      if (!ws || ws.readyState !== WebSocket.OPEN) return;
      setSending(true);
      addMessage({
        id: makeMessageId(),
        role: 'user',
        content,
        timestamp: Date.now(),
      });
      ws.send(JSON.stringify({ type: 'message', message: content, user_id: userId }));
    },
    [addMessage, setSending],
  );

  const reconnect = useCallback(() => {
    retryRef.current = 0;
    wsRef.current?.close();
    connect();
  }, [connect]);

  return { sendMessage, reconnect, onReflectionRef };
}
