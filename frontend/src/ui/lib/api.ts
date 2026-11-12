'use client';

export class ApiError extends Error {
  constructor(public status: number, message: string, public code?: string) {
    super(message);
  }
}

function detailMessage(body: unknown, status: number): string {
  const d = (body as { detail?: unknown } | null)?.detail;
  if (typeof d === 'string') return d;
  if (d && typeof d === 'object' && 'message' in d) return String((d as { message: unknown }).message);
  // FastAPI validation errors: [{loc, msg}, ...]
  if (Array.isArray(d) && d.length) {
    return d
      .map((e: { loc?: unknown[]; msg?: string }) => {
        const field = e.loc?.filter((p) => p !== 'body').join('.');
        return field ? `${field}: ${e.msg}` : e.msg;
      })
      .join('; ');
  }
  return `Request failed (HTTP ${status})`;
}

/** JSON fetch against the FastAPI backend (proxied by Next at /api).
 * A 401 anywhere means the session ended — bounce to /login. */
export async function api<T>(path: string, init?: { method?: string; body?: unknown }): Promise<T> {
  const res = await fetch(`/api${path}`, {
    method: init?.method ?? 'GET',
    headers: init?.body !== undefined ? { 'Content-Type': 'application/json' } : undefined,
    body: init?.body !== undefined ? JSON.stringify(init.body) : undefined,
    credentials: 'same-origin',
    cache: 'no-store',
  });
  if (res.status === 401 && !path.startsWith('/auth/')) {
    window.location.href = '/login';
    throw new ApiError(401, 'Signed out');
  }
  if (res.status === 204) return undefined as T;
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    const d = (body as { detail?: { code?: string } } | null)?.detail;
    throw new ApiError(res.status, detailMessage(body, res.status), typeof d === 'object' && d ? d.code : undefined);
  }
  return body as T;
}

/** Build a query string, skipping empty values. */
export function qs(params: Record<string, string | number | boolean | null | undefined>): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === '' || v === false) continue;
    p.set(k, String(v));
  }
  const s = p.toString();
  return s ? `?${s}` : '';
}
