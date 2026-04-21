/**
 * Client-side feature flag resolution.
 *
 * For Phase 1 the only flag is `new_ui`. Mirrors the backend FF_NEW_UI,
 * but the backend value isn't wired to the frontend yet so the flip lives
 * in query string / localStorage.
 *
 * Resolution order (first match wins):
 *   1. URL query `?ui=new` → set, `?ui=old` → unset, persisted to localStorage
 *   2. localStorage `analytica.ff.new_ui` = "1"
 *   3. window.__ANALYTICA_FF__.new_ui (for e2e tests)
 *   4. false
 */

const LS_KEY = 'analytica.ff.new_ui';

declare global {
  interface Window {
    __ANALYTICA_FF__?: Record<string, boolean | undefined>;
  }
}

export function isNewUIEnabled(): boolean {
  if (typeof window === 'undefined') return false;
  try {
    const params = new URLSearchParams(window.location.search);
    const uiParam = params.get('ui');
    if (uiParam === 'new') {
      window.localStorage.setItem(LS_KEY, '1');
      return true;
    }
    if (uiParam === 'old') {
      window.localStorage.removeItem(LS_KEY);
      return false;
    }
    if (window.localStorage.getItem(LS_KEY) === '1') return true;
    if (window.__ANALYTICA_FF__?.new_ui) return true;
  } catch {
    /* localStorage may be unavailable in private mode */
  }
  return false;
}

export function setNewUIEnabled(enabled: boolean): void {
  if (typeof window === 'undefined') return;
  try {
    if (enabled) window.localStorage.setItem(LS_KEY, '1');
    else window.localStorage.removeItem(LS_KEY);
  } catch {
    /* noop */
  }
}
