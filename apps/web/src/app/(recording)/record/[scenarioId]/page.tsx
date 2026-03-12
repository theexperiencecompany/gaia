import RecordingPage from "@/features/recording/components/RecordingPage";

interface Props {
  params: Promise<{ scenarioId: string }>;
}

export default async function RecordPage({ params }: Props) {
  const { scenarioId } = await params;
  return <RecordingPage scenarioId={scenarioId} />;
}
