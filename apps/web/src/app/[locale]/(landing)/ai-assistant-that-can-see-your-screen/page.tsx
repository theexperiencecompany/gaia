import GuideLanding from "@/components/seo/GuideLanding";
import { generateGuideMetadata } from "@/components/seo/guideLandingMetadata";

const SLUG = "ai-assistant-that-can-see-your-screen";

export function generateMetadata() {
  return generateGuideMetadata(SLUG);
}

export default function AiAssistantSeeScreenPage() {
  return <GuideLanding slug={SLUG} />;
}
