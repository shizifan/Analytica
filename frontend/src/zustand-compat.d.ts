/**
 * Ambient type shim for zustand 5 + TypeScript 6 + moduleResolution:bundler.
 *
 * TypeScript 6 cannot resolve zustand 5's package exports through bundler
 * module resolution. This file provides minimal types as a fallback:
 * TypeScript uses ambient declarations only when node_modules resolution
 * fails, so in environments where zustand resolves correctly (e.g., future
 * TS versions), the real package types take precedence.
 */

type ZustandSetState<T> =
  | Partial<T>
  | T
  | ((state: T) => Partial<T> | T);

type ZustandSet<T> = (
  partial: ZustandSetState<T>,
  replace?: boolean,
) => void;

type ZustandGet<T> = () => T;

interface ZustandStoreApi<T> {
  getState(): T;
  setState(partial: ZustandSetState<T>, replace?: boolean): void;
  subscribe(listener: (state: T, prevState: T) => void): () => void;
}

type ZustandUseBoundStore<T> = {
  (): T;
} & ZustandStoreApi<T>;

declare module 'zustand/react' {
  export function create<T>(
    initializer: (
      set: ZustandSet<T>,
      get: ZustandGet<T>,
      store: ZustandStoreApi<T>,
    ) => T,
  ): ZustandUseBoundStore<T>;
}

declare module 'zustand' {
  export { create } from 'zustand/react';
}
