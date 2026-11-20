import { Suspense } from 'react';
import { LoansPage } from '@/ui/pages/Loans';

export default function Page() {
  return (
    <Suspense>
      <LoansPage />
    </Suspense>
  );
}
