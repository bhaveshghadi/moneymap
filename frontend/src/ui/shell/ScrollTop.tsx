'use client';
import { useEffect, useRef, useState, type RefObject } from 'react';
import { Icon } from '../primitives/Icon';

const easeInOutCubic = (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);

/** Round "back to top" button, bottom-right, shown once the page is scrolled
 * down a screen or so. `.content` is the scroller (the shell doesn't scroll).
 * Scrolls with its own eased animation (same feel on every browser and even
 * when Windows animations are off); a wheel/touch/key stops it. */
export function ScrollTop({ scroller }: { scroller: RefObject<HTMLDivElement | null> }) {
  const [show, setShow] = useState(false);
  const frame = useRef<number | null>(null);

  useEffect(() => {
    const el = scroller.current;
    if (!el) return;
    const onScroll = () => setShow(el.scrollTop > Math.max(400, el.clientHeight * 0.6));
    const stop = () => {
      if (frame.current !== null) cancelAnimationFrame(frame.current);
      frame.current = null;
    };
    onScroll();
    el.addEventListener('scroll', onScroll, { passive: true });
    el.addEventListener('wheel', stop, { passive: true });
    el.addEventListener('touchstart', stop, { passive: true });
    window.addEventListener('keydown', stop);
    return () => {
      stop();
      el.removeEventListener('scroll', onScroll);
      el.removeEventListener('wheel', stop);
      el.removeEventListener('touchstart', stop);
      window.removeEventListener('keydown', stop);
    };
  }, [scroller]);

  const up = () => {
    const el = scroller.current;
    if (!el || frame.current !== null) return;
    const from = el.scrollTop;
    // 450ms for a short page, up to 900ms for a very long one
    const duration = Math.min(900, 450 + from / 12);
    const t0 = performance.now();
    const step = (now: number) => {
      const t = Math.min(1, (now - t0) / duration);
      el.scrollTop = Math.round(from * (1 - easeInOutCubic(t)));
      frame.current = t < 1 ? requestAnimationFrame(step) : null;
    };
    frame.current = requestAnimationFrame(step);
  };

  return (
    <button type="button" className={`scroll-top ${show ? 'on' : ''}`} onClick={up} title="Back to top" aria-label="Back to top" tabIndex={show ? 0 : -1} aria-hidden={!show}>
      <Icon name="arrow-up" size={20} />
    </button>
  );
}
