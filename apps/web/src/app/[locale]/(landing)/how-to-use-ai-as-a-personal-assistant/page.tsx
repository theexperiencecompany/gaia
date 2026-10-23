import GuideLanding from "@/components/seo/GuideLanding";
import { generateGuideMetadata } from "@/components/seo/guideLandingMetadata";

const SLUG = "how-to-use-ai-as-a-personal-assistant";

export function generateMetadata() {
  return generateGuideMetadata(SLUG);
}

export default function HowToUseAiAsPersonalAssistantPage() {
  return <GuideLanding slug={SLUG} />;
}
