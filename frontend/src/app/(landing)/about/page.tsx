import type { Metadata } from "next";

import About from "@/features/about/components/About";
import { generatePageMetadata } from "@/lib/seo";

export const metadata: Metadata = generatePageMetadata({
  title: "About GAIA",
  description:
    "Meet the founders behind GAIA and learn why we're building a personal AI assistant that actually does things for you. Discover our vision for a privacy-first, open-source assistant that handles emails, meetings, scheduling, and more—like Jarvis from Iron Man.",
  path: "/about",
  keywords: [
    "About GAIA",
    "GAIA founders",
    "personal AI assistant",
    "open source assistant",
    "privacy-first AI",
    "AI productivity",
    "email automation",
    "meeting scheduler",
    "Jarvis AI",
    "General-purpose AI Assistant",
  ],
});

export default function AboutPage() {
  return <About />;
}
