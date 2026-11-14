import { Suspense } from 'react';
import { StatementsPage } from '@/ui/pages/Statements';

export default function Page() {
  return (
    <Suspense>
      <StatementsPage />
    </Suspense>
  );
}
