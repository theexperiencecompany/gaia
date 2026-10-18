import GuideLanding from "@/components/seo/GuideLanding";
import { generateGuideMetadata } from "@/components/seo/guideLandingMetadata";

const SLUG = "ai-assistant-like-jarvis";

export function generateMetadata() {
  return generateGuideMetadata(SLUG);
}

export default function AiAssistantLikeJarvisPage() {
  return <GuideLanding slug={SLUG} />;
}
