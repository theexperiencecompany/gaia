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
  title: "The GAIA Manifesto: Why We Build a Proactive AI",
  description:
    "Why we are building GAIA: an assistant that remembers you, does the work instead of only answering, and keeps your data private. Read the manifesto.",
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
  const aboutSchema = generateAboutPageSchema();
  const webPageSchema = generateWebPageSchema(
    "Manifesto",
    "Read why we're building GAIA differently. Our commitment to privacy, open source, and building AI that actually helps.",
    `${siteConfig.url}/manifesto`,
    [
      { name: "Home", url: siteConfig.url },
      { name: "Manifesto", url: `${siteConfig.url}/manifesto` },
    ],
  );
  const breadcrumbSchema = generateBreadcrumbSchema([
    { name: "Home", url: siteConfig.url },
    { name: "Manifesto", url: `${siteConfig.url}/manifesto` },
  ]);

  return (
    <>
      {/* No FAQPage schema here: this page renders no visible FAQs,
          and FAQ rich results require the questions to be on the page. */}
      <JsonLd data={[aboutSchema, webPageSchema, breadcrumbSchema]} />
      <About />
    </>
  );
}
