import { Suspense } from 'react';
import { InvestmentDetailPage } from '@/ui/pages/InvestmentDetail';

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return (
    <Suspense>
      <InvestmentDetailPage id={Number(id)} />
    </Suspense>
  );
}
