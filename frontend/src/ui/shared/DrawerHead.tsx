'use client';
import type { ReactNode } from 'react';
import { Icon } from '../primitives/Icon';
import { useDialogClose } from '../primitives/Dialog';

/** `.drawer-head` with title, subtitle and the animated close button. */
export function DrawerHead({ title, sub, lead }: { title: ReactNode; sub?: ReactNode; lead?: ReactNode }) {
  const close = useDialogClose();
  return (
    <div className="drawer-head">
      <div style={{ display: 'flex', gap: 12, alignItems: 'flex-start', minWidth: 0 }}>
        {lead}
        <div style={{ minWidth: 0 }}>
          <h3>{title}</h3>
          {sub && <p>{sub}</p>}
        </div>
      </div>
      <button type="button" className="drawer-x" aria-label="Close" onClick={close}>
        <Icon name="x" size={18} />
      </button>
    </div>
  );
}
