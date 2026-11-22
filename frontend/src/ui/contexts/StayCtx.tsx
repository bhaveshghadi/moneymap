'use client';
import { createContext, useContext, type ReactNode } from 'react';

/** Inside the setup page, forms save and close without opening the item's own page. */
const StayCtx = createContext(false);

export function StayProvider({ children }: { children: ReactNode }) {
  return <StayCtx.Provider value={true}>{children}</StayCtx.Provider>;
}

export const useStay = () => useContext(StayCtx);
