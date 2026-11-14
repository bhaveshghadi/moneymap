import { Suspense } from 'react';
import { CardDetailPage } from '@/ui/pages/CardDetail';

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return (
    <Suspense>
      <CardDetailPage id={Number(id)} />
    </Suspense>
  );
}
