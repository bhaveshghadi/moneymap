import { Suspense } from 'react';
import { StatementReviewPage } from '@/ui/pages/StatementReview';

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return (
    <Suspense>
      <StatementReviewPage id={Number(id)} />
    </Suspense>
  );
}
