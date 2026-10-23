import { BriefingPage } from "@/features/briefing";

interface BriefPageProps {
  params: Promise<{ id: string }>;
}

export default async function BriefPage({ params }: BriefPageProps) {
  const { id } = await params;
  return <BriefingPage briefingId={id} />;
}
