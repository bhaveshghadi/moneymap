import { Suspense } from 'react';
import { SettingsPage } from '@/ui/pages/Settings';

export default function Page() {
  return (
    <Suspense>
      <SettingsPage />
    </Suspense>
  );
}
