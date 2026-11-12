import { Suspense } from 'react';
import { AccountsPage } from '@/ui/pages/Accounts';

export default function Page() {
  return (
    <Suspense>
      <AccountsPage />
    </Suspense>
  );
}
