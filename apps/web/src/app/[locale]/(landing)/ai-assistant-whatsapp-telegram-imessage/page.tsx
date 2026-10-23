import GuideLanding from "@/components/seo/GuideLanding";
import { generateGuideMetadata } from "@/components/seo/guideLandingMetadata";

const SLUG = "ai-assistant-whatsapp-telegram-imessage";

export function generateMetadata() {
  return generateGuideMetadata(SLUG);
}

export default function AiAssistantMessagingPage() {
  return <GuideLanding slug={SLUG} />;
}
