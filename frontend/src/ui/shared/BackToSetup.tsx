'use client';
import { useEffect, useState } from 'react';
import Link from 'next/link';
import { Icon } from '../primitives/Icon';

/** On a review page opened from the setup page (?from=setup): the way back to it. */
export function BackToSetup({ step }: { step: string }) {
  const [show, setShow] = useState(false);
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- the query is only readable in the browser
    setShow(new URLSearchParams(window.location.search).get('from') === 'setup');
  }, []);
  if (!show) return null;
  return (
    <div className="note info" style={{ marginBottom: 14 }}>
      <Icon name="compass" size={15} />
      <span>
        You came here from the setup page. When you&apos;re done here,{' '}
        <Link href={`/welcome?step=${step}`}><b>go back to setup</b></Link>.
      </span>
    </div>
  );
}
