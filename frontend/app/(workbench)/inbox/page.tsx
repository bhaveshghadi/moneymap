import { Suspense } from 'react';
import { InboxPage } from '@/ui/pages/Inbox';

export default function Page() {
  return (
    <Suspense>
      <InboxPage />
    </Suspense>
  );
}
