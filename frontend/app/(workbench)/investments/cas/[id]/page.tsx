import { CasReviewPage } from '@/ui/pages/CasReview';

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <CasReviewPage id={Number(id)} />;
}
