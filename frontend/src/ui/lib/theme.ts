'use client';
import { useEffect, useState } from 'react';

/** Light / dark / follow the device. Kept per browser (localStorage), so a phone and a PC can differ. */
export type ThemeChoice = 'light' | 'dark' | 'system';

export const THEME_KEY = 'mm-theme';
const DARK_QUERY = '(prefers-color-scheme: dark)';

export function readChoice(): ThemeChoice {
  try {
    const v = localStorage.getItem(THEME_KEY);
    return v === 'light' || v === 'dark' ? v : 'system';
  } catch {
    return 'system';
  }
}

export function applyTheme(choice: ThemeChoice): void {
  const dark = choice === 'dark' || (choice === 'system' && window.matchMedia(DARK_QUERY).matches);
  const root = document.documentElement;
  if (root.dataset.theme === (dark ? 'dark' : 'light')) return;
  // switch in one step: without this every input and button fades between the two colour sets
  root.classList.add('theme-switching');
  root.dataset.theme = dark ? 'dark' : 'light';
  requestAnimationFrame(() => requestAnimationFrame(() => root.classList.remove('theme-switching')));
}

/** Runs in <head> before the page paints, so a dark page never flashes white. Same logic as above. */
export const THEME_BOOT = `(function(){try{var c=localStorage.getItem('${THEME_KEY}');var d=c==='dark'||(c!=='light'&&window.matchMedia('${DARK_QUERY}').matches);document.documentElement.dataset.theme=d?'dark':'light';}catch(e){}})();`;

/** Keeps the page in step: the device switching light/dark ("Match system"), or another tab changing the choice. */
export function ThemeWatcher() {
  useEffect(() => {
    const mq = window.matchMedia(DARK_QUERY);
    const sync = () => applyTheme(readChoice());
    const onStorage = (e: StorageEvent) => e.key === THEME_KEY && sync();
    mq.addEventListener('change', sync);
    window.addEventListener('storage', onStorage);
    return () => {
      mq.removeEventListener('change', sync);
      window.removeEventListener('storage', onStorage);
    };
  }, []);
  return null;
}

export function useTheme(): [ThemeChoice, (c: ThemeChoice) => void] {
  const [choice, setChoice] = useState<ThemeChoice>('system');
  // eslint-disable-next-line react-hooks/set-state-in-effect -- localStorage is only readable after mount
  useEffect(() => setChoice(readChoice()), []);
  const set = (c: ThemeChoice) => {
    try {
      if (c === 'system') localStorage.removeItem(THEME_KEY);
      else localStorage.setItem(THEME_KEY, c);
    } catch {
      /* private window: still applies for this page */
    }
    setChoice(c);
    applyTheme(c);
  };
  return [choice, set];
}
