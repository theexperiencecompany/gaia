import type { Metadata } from "next";
import JsonLd from "@/components/seo/JsonLd";
import { AGENCY_FAQS } from "@/features/landing/data/personaFaqs";
import {
  generateBreadcrumbSchema,
  generateFAQSchema,
  generateWebPageSchema,
  siteConfig,
} from "@/lib/seo";
import AgencyClient from "./AgencyClient";

export const metadata: Metadata = {
  title: "For Agency Owners: Run 10 Clients Without Losing Your Mind",
  description:
    "GAIA monitors your client portfolio, writes status reports, and keeps your pipeline moving, while you focus on the work that actually grows your agency.",
  alternates: {
    canonical: "/for/agency-owners",
  },
};

export default function AgencyOwnersPage() {
  const pageUrl = `${siteConfig.url}/agency-owners`;
  const breadcrumbs = [
    { name: "Home", url: siteConfig.url },
    { name: "For Agency Owners", url: pageUrl },
  ];

  return (
    <>
      <JsonLd
        data={[
          generateWebPageSchema(
            "For Agency Owners: Run 10 Clients Without Losing Your Mind",
            "GAIA monitors your client portfolio, writes status reports, and keeps your pipeline moving, while you focus on the work that actually grows your agency.",
            pageUrl,
            breadcrumbs,
          ),
          generateBreadcrumbSchema(breadcrumbs),
          generateFAQSchema(AGENCY_FAQS),
        ]}
      />
      <AgencyClient />
    </>
  );
}
