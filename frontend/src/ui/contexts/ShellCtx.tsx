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

/** Fetch `path` (null = skip). Refetches when the path or shell version changes. */
export function useApi<T>(path: string | null): {
  data: T | null;
  error: string | null;
  loading: boolean;
  reload: () => void;
} {
  const { version } = useShell();
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(path !== null);
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    if (path === null) return;
    let cancelled = false;
    setLoading(true);
    api<T>(path)
      .then((d) => {
        if (cancelled) return;
        setData(d);
        setError(null);
      })
      .catch((e: Error) => {
        if (!cancelled) setError(e.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [path, version, nonce]);

  return { data, error, loading, reload: () => setNonce((n) => n + 1) };
}
