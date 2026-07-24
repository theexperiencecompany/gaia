import type { Metadata } from "next";

import { PublicArtifactView } from "@/features/short-links/components/PublicArtifactView";

export const metadata: Metadata = {
  title: "Artifact",
};

interface PageProps {
  params: Promise<{ slug: string }>;
}

// Public capability-link page: lives OUTSIDE the (main) route group on purpose,
// so a signed-out viewer (tapping a briefing link inside Telegram) never mounts
// the authed app shell or its onboarding/auth guards.
export default async function ShortLinkPage({ params }: PageProps) {
  const { slug } = await params;
  return <PublicArtifactView slug={slug} />;
}
