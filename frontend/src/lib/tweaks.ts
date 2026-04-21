import { create } from 'zustand';

export type TweakTheme = 'light' | 'dark';
export type TweakDensity = 'compact' | 'comfortable' | 'spacious';
export type TweakAccent = 'teal' | 'violet' | 'amber' | 'green';
export type TweakLayout = 'three-pane' | 'two-pane' | 'focus';

export interface TweakState {
  theme: TweakTheme;
  density: TweakDensity;
  accent: TweakAccent;
  layout: TweakLayout;
  setTheme: (v: TweakTheme) => void;
  setDensity: (v: TweakDensity) => void;
  setAccent: (v: TweakAccent) => void;
  setLayout: (v: TweakLayout) => void;
}

const LS_KEY = 'analytica.tweaks.v1';

const defaults = {
  theme: 'light' as TweakTheme,
  density: 'comfortable' as TweakDensity,
  accent: 'teal' as TweakAccent,
  layout: 'three-pane' as TweakLayout,
};

function load(): Pick<TweakState, 'theme' | 'density' | 'accent' | 'layout'> {
  if (typeof window === 'undefined') return defaults;
  try {
    const raw = window.localStorage.getItem(LS_KEY);
    if (!raw) return defaults;
    const parsed = JSON.parse(raw);
    return { ...defaults, ...parsed };
  } catch {
    return defaults;
  }
}

function persist(partial: Partial<TweakState>) {
  if (typeof window === 'undefined') return;
  try {
    const current = load();
    window.localStorage.setItem(
      LS_KEY,
      JSON.stringify({ ...current, ...partial }),
    );
  } catch {
    /* noop */
  }
}

export const useTweakStore = create<TweakState>((set) => ({
  ...load(),
  setTheme: (v) => {
    persist({ theme: v });
    set({ theme: v });
  },
  setDensity: (v) => {
    persist({ density: v });
    set({ density: v });
  },
  setAccent: (v) => {
    persist({ accent: v });
    set({ accent: v });
  },
  setLayout: (v) => {
    persist({ layout: v });
    set({ layout: v });
  },
}));

/**
 * Apply tweak attributes to <html>. Accent `teal` is the default palette, so
 * we only set the attribute for non-default accents.
 */
export function applyTweaksToDocument(state: TweakState): void {
  if (typeof document === 'undefined') return;
  const root = document.documentElement;
  root.setAttribute('data-theme', state.theme);
  root.setAttribute('data-density', state.density);
  root.setAttribute('data-layout', state.layout);
  if (state.accent === 'teal') root.removeAttribute('data-accent');
  else root.setAttribute('data-accent', state.accent);
}
