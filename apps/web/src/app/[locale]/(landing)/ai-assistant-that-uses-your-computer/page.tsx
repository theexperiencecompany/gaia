import GuideLanding from "@/components/seo/GuideLanding";
import { generateGuideMetadata } from "@/components/seo/guideLandingMetadata";

const SLUG = "ai-assistant-that-uses-your-computer";

export function generateMetadata() {
  return generateGuideMetadata(SLUG);
}

export default function AiAssistantUsesComputerPage() {
  return <GuideLanding slug={SLUG} />;
}
