import { Suspense } from 'react';
import { TransactionsPage } from '@/ui/pages/Transactions';

export default function Page() {
  return (
    <Suspense>
      <TransactionsPage />
    </Suspense>
  );
}
