import { readFileSync } from "node:fs";
import { join } from "node:path";

import RecordingPage from "@/features/recording/components/RecordingPage";

interface Props {
  params: Promise<{ scenarioId: string }>;
}

export default async function RecordPage({ params }: Props) {
  const { scenarioId } = await params;

  let scenarioData: unknown = null;
  try {
    const filePath = join(
      process.cwd(),
      "public",
      "scenarios",
      `${scenarioId}.json`,
    );
    scenarioData = JSON.parse(readFileSync(filePath, "utf-8"));
  } catch {
    // Client will fetch and show error
  }

  return <RecordingPage scenarioId={scenarioId} scenarioData={scenarioData} />;
}
