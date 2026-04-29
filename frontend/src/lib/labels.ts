/**
 * Shared display labels for session phase and websocket status.
 *
 * Single source of truth — used by Topbar (full pill) and ChatPageV2
 * (compact phase chip in AgentPane header).
 */

export const PHASE_LABELS: Record<string, string> = {
  idle: '待机',
  perception: '感知中',
  planning: '规划中',
  executing: '执行中',
  reflection: '反思中',
  done: '已完成',
};

export const WS_LABELS: Record<string, string> = {
  connected: 'connected',
  connecting: 'connecting',
  disconnected: 'disconnected',
  failed: 'failed',
};
