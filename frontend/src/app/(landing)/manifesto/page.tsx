import type { Metadata } from "next";

import About from "@/features/about/components/About";
import { generatePageMetadata } from "@/lib/seo";

export const metadata: Metadata = generatePageMetadata({
  title: "Manifesto",
  description:
    "Read why we're building GAIA differently. Unlike Siri, Alexa, or ChatGPT, GAIA is designed to be a real assistant that remembers you, handles your work, and makes your life easier. Learn about our commitment to privacy, open source, and building AI that actually helps.",
  path: "/manifesto",
  keywords: [
    "GAIA manifesto",
    "AI assistant vision",
    "personal assistant",
    "open source AI",
    "privacy focused AI",
    "proactive AI",
    "AI automation",
    "digital assistant",
    "AI transparency",
    "future of AI",
  ],
});

export default function Manifesto() {
  return <About />;
}
