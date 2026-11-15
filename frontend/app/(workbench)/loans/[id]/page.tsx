import { Suspense } from 'react';
import { LoanDetailPage } from '@/ui/pages/LoanDetail';

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return (
    <Suspense>
      <LoanDetailPage id={Number(id)} />
    </Suspense>
  );
}
