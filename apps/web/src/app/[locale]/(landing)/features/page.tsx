import type { Metadata } from "next";
import { FeaturesAtAGlance } from "@/features/landing/components/features/FeaturesAtAGlance";
import { FeaturesGrid } from "@/features/landing/components/features/FeaturesGrid";
import { generatePageMetadata } from "@/lib/seo";

export const metadata: Metadata = generatePageMetadata({
  title: "Features: Email, Calendar, Tasks, Workflows and Memory",
  description:
    "Every GAIA feature in one list: email triage, calendar, todos, plain-English workflows, memory, MCP, WhatsApp, Telegram, Slack and the desktop app.",
  path: "/features",
});

export default function FeaturesPage() {
  return (
    <FeaturesGrid>
      <FeaturesAtAGlance />
    </FeaturesGrid>
  );
}
