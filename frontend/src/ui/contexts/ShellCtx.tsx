'use client';
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react';
import { api } from '../lib/api';

interface ShellCtxValue {
  username: string | null;
  /** Bumped after any mutation; data hooks refetch when it changes. */
  version: number;
  bump: () => void;
}

const ShellCtx = createContext<ShellCtxValue>({ username: null, version: 0, bump: () => {} });

export function ShellProvider({ username, children }: { username: string | null; children: ReactNode }) {
  const [version, setVersion] = useState(0);
  const bump = useCallback(() => setVersion((v) => v + 1), []);
  return <ShellCtx.Provider value={{ username, version, bump }}>{children}</ShellCtx.Provider>;
}

export function useShell(): ShellCtxValue {
  return useContext(ShellCtx);
}

/** Fetch `path` (null = skip). Refetches when the path or shell version changes.
 *
 * The previous data stays visible while a new request runs. `loading` is worked
 * out from which request the stored result belongs to, so the effect only sets
 * state when a response arrives (no synchronous setState inside the effect). */
export function useApi<T>(path: string | null): {
  data: T | null;
  error: string | null;
  loading: boolean;
  reload: () => void;
} {
  const { version } = useShell();
  const [nonce, setNonce] = useState(0);
  const key = path === null ? null : `${path}#${version}#${nonce}`;
  const [result, setResult] = useState<{ key: string | null; data: T | null; error: string | null }>({
    key: null,
    data: null,
    error: null,
  });

  useEffect(() => {
    if (path === null || key === null) return;
    let cancelled = false;
    api<T>(path)
      .then((d) => {
        if (!cancelled) setResult({ key, data: d, error: null });
      })
      .catch((e: Error) => {
        if (!cancelled) setResult((prev) => ({ key, data: prev.data, error: e.message }));
      });
    return () => {
      cancelled = true;
    };
  }, [path, key]);

  const reload = useCallback(() => setNonce((n) => n + 1), []);
  return { data: result.data, error: result.error, loading: key !== null && result.key !== key, reload };
}
