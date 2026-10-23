import GuideLanding from "@/components/seo/GuideLanding";
import { generateGuideMetadata } from "@/components/seo/guideLandingMetadata";

const SLUG = "ai-assistant-with-memory";

export function generateMetadata() {
  return generateGuideMetadata(SLUG);
}

export default function AiAssistantWithMemoryPage() {
  return <GuideLanding slug={SLUG} />;
}
