'use client';
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import { MaskProvider } from '../contexts/MaskCtx';
import { ShellProvider } from '../contexts/ShellCtx';
import { TxnProvider } from '../contexts/TxnCtx';
import { api } from '../lib/api';
import type { AuthStatus } from '../lib/types';
import { Sidebar } from './Sidebar';
import { Topbar } from './Topbar';
import { ScrollTop } from './ScrollTop';
import { ChoosePassword } from './ChoosePassword';

/**
 * Persistent workbench chrome: providers + sidebar +
 * topbar around the routed page. Checks the session first and sends
 * signed-out or first-run visitors to /login.
 */
export function WorkbenchShell({ children, bare = false }: { children: ReactNode; bare?: boolean }) {
  const router = useRouter();
  const pathname = usePathname();
  const contentRef = useRef<HTMLDivElement | null>(null);
  const [status, setStatus] = useState<AuthStatus | null>(null);

  useEffect(() => {
    api<AuthStatus>('/auth/status')
      .then((s) => {
        if (!s.authenticated) router.replace('/login');
        else setStatus(s);
      })
      .catch(() => router.replace('/login'));
  }, [router]);

  // `.content` is the scroller (the shell grid is overflow:hidden) — reset per route.
  useEffect(() => {
    if (contentRef.current) contentRef.current.scrollTop = 0;
  }, [pathname]);

  if (!status) {
    return (
      <div className="boot" aria-label="Loading">
        <div className="boot-bar"><i /></div>
      </div>
    );
  }

  if (status.must_change_password) {
    // signed in with the temporary password the admin gave: choose your own first
    return <ChoosePassword status={status} onDone={(s) => setStatus(s)} />;
  }

  if (bare) {
    // the setup page: signed in, full screen, no sidebar / top bar
    return (
      <MaskProvider>
        <ShellProvider username={status.username} displayName={status.display_name ?? null} isAdmin={!!status.is_admin}>
          <TxnProvider>{children}</TxnProvider>
        </ShellProvider>
      </MaskProvider>
    );
  }

  return (
    <MaskProvider>
      <ShellProvider username={status.username} displayName={status.display_name ?? null} isAdmin={!!status.is_admin}>
        <TxnProvider>
          <div className="app-enter">
            <div className="app">
              <Sidebar />
              <div className="main">
                <Topbar />
                <div className="content" ref={contentRef}>
                  {children}
                </div>
              </div>
            </div>
          </div>
          <ScrollTop scroller={contentRef} />
        </TxnProvider>
      </ShellProvider>
    </MaskProvider>
  );
}
