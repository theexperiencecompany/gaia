import type { Metadata } from "next";
import JsonLd from "@/components/seo/JsonLd";
import { EM_FAQS } from "@/features/landing/data/personaFaqs";
import {
  generateBreadcrumbSchema,
  generateFAQSchema,
  generateWebPageSchema,
  siteConfig,
} from "@/lib/seo";
import EngineeringManagerClient from "./EngineeringManagerClient";

export const metadata: Metadata = {
  title:
    "GAIA for Engineering Managers: Lead Your Team Without Losing Technical Context",
  description:
    "GAIA monitors GitHub, Linear, and Slack so you don't have to. It preps your 1:1s, surfaces team blockers, and keeps you informed, without reading every thread.",
  alternates: {
    canonical: "/for/engineering-managers",
  },
};

export default function EngineeringManagersPage() {
  const pageUrl = `${siteConfig.url}/engineering-managers`;
  const breadcrumbs = [
    { name: "Home", url: siteConfig.url },
    { name: "For Engineering Managers", url: pageUrl },
  ];

  return (
    <>
      <JsonLd
        data={[
          generateWebPageSchema(
            "GAIA for Engineering Managers: Lead Your Team Without Losing Technical Context",
            "GAIA monitors GitHub, Linear, and Slack so you don't have to. It preps your 1:1s, surfaces team blockers, and keeps you informed, without reading every thread.",
            pageUrl,
            breadcrumbs,
          ),
          generateBreadcrumbSchema(breadcrumbs),
          generateFAQSchema(EM_FAQS),
        ]}
      />
      <EngineeringManagerClient />
    </>
  );
}
