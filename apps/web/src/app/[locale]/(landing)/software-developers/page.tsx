import type { Metadata } from "next";
import JsonLd from "@/components/seo/JsonLd";
import { SOFTWARE_DEV_FAQS } from "@/features/landing/data/personaFaqs";
import {
  generateBreadcrumbSchema,
  generateFAQSchema,
  generateWebPageSchema,
  siteConfig,
} from "@/lib/seo";
import SoftwareDevClient from "./SoftwareDevClient";

export const metadata: Metadata = {
  title: "For Software Developers: Ship Code, Not Status Updates",
  description:
    "GAIA monitors GitHub, Linear, and Slack in the background, triages what needs you, handles the rest, and delivers your standup before your first commit.",
  alternates: {
    canonical: "/for/software-developers",
  },
};

export default function SoftwareDevelopersPage() {
  const pageUrl = `${siteConfig.url}/software-developers`;
  const breadcrumbs = [
    { name: "Home", url: siteConfig.url },
    { name: "For Software Developers", url: pageUrl },
  ];

  return (
    <>
      <JsonLd
        data={[
          generateWebPageSchema(
            "For Software Developers: Ship Code, Not Status Updates",
            "GAIA monitors GitHub, Linear, and Slack in the background, triages what needs you, handles the rest, and delivers your standup before your first commit.",
            pageUrl,
            breadcrumbs,
          ),
          generateBreadcrumbSchema(breadcrumbs),
          generateFAQSchema(SOFTWARE_DEV_FAQS),
        ]}
      />
      <SoftwareDevClient />
    </>
  );
}
