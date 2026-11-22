import { Suspense } from 'react';
import { SetupPage } from '@/ui/pages/Setup';

export default function Page() {
  return (
    <Suspense>
      <SetupPage />
    </Suspense>
  );
}
