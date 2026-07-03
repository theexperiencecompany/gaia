import type { Metadata } from "next";

import ArtifactReader from "@/features/short-links/components/ArtifactReader";

export const metadata: Metadata = {
  title: "Artifact",
};

interface PageProps {
  params: Promise<{ todoId: string }>;
}

export default async function ArtifactPage({ params }: PageProps) {
  const { todoId } = await params;
  return <ArtifactReader todoId={todoId} />;
}
