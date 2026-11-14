import type { Metadata } from "next";

import JsonLd from "@/components/seo/JsonLd";
import Thanks from "@/features/thanks/components/Thanks";
import {
  generateBreadcrumbSchema,
  generatePageMetadata,
  generateWebPageSchema,
  siteConfig,
} from "@/lib/seo";

export const metadata: Metadata = generatePageMetadata({
  title: "Tools We Love: The Open-Source Projects Behind GAIA",
  description:
    "The open-source projects and tools GAIA is built on, and the communities and maintainers behind them. A thank-you list from the GAIA team.",
  path: "/thanks",
  keywords: [
    "open source",
    "developer tools",
    "software tools",
    "GAIA stack",
    "tech stack",
    "developer ecosystem",
    "open source community",
    "software infrastructure",
  ],
});

export default function ThanksPage() {
  const webPageSchema = generateWebPageSchema(
    "Tools We Love",
    "Discover the incredible open-source projects and tools that power GAIA.",
    `${siteConfig.url}/thanks`,
    [
      { name: "Home", url: siteConfig.url },
      { name: "Tools We Love", url: `${siteConfig.url}/thanks` },
    ],
  );
  const breadcrumbSchema = generateBreadcrumbSchema([
    { name: "Home", url: siteConfig.url },
    { name: "Tools We Love", url: `${siteConfig.url}/thanks` },
  ]);

  return (
    <>
      <JsonLd data={[webPageSchema, breadcrumbSchema]} />
      <Thanks />
    </>
  );
}
