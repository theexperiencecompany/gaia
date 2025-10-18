import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { generatePageMetadata } from "@/lib/seo";

export const metadata: Metadata = generatePageMetadata({
  title: "About GAIA",
  description:
    "Learn about GAIA's mission to build a personal AI assistant for everyone. Discover our vision for proactive AI, open-source commitment, and privacy-first approach to productivity.",
  path: "/about",
  keywords: [
    "About GAIA",
    "GAIA Manifesto",
    "AI Assistant Vision",
    "Open Source AI",
    "Privacy-First AI",
    "Founders Story",
    "GAIA Mission",
    "Personal Assistant Vision",
  ],
});

export default function AboutPage() {
  redirect("/manifesto");
}
