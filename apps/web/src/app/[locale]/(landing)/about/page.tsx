import type { Metadata } from "next";

import JsonLd from "@/components/seo/JsonLd";
import About from "@/features/about/components/About";
import {
  generateAboutPageSchema,
  generateBreadcrumbSchema,
  generatePageMetadata,
  generateWebPageSchema,
  siteConfig,
} from "@/lib/seo";

export const metadata: Metadata = generatePageMetadata({
  title: "About",
  description:
    "Meet the founders behind GAIA and why they are building a personal AI assistant that does the work: email, meetings, and scheduling. Read the story and vision.",
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
  const aboutSchema = generateAboutPageSchema();
  const webPageSchema = generateWebPageSchema(
    "About GAIA",
    "Meet the founders behind GAIA and learn why we're building a personal AI assistant.",
    `${siteConfig.url}/about`,
    [
      { name: "Home", url: siteConfig.url },
      { name: "About", url: `${siteConfig.url}/about` },
    ],
  );
  const breadcrumbSchema = generateBreadcrumbSchema([
    { name: "Home", url: siteConfig.url },
    { name: "About", url: `${siteConfig.url}/about` },
  ]);

  return (
    <>
      <JsonLd data={[aboutSchema, webPageSchema, breadcrumbSchema]} />
      <About />
    </>
  );
}
