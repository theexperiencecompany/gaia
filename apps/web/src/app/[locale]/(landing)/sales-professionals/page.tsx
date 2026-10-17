import type { Metadata } from "next";
import JsonLd from "@/components/seo/JsonLd";
import { SALES_FAQS } from "@/features/landing/data/personaFaqs";
import {
  generateBreadcrumbSchema,
  generateFAQSchema,
  generateWebPageSchema,
  siteConfig,
} from "@/lib/seo";
import SalesClient from "./SalesClient";

export const metadata: Metadata = {
  title: "For Sales: You're Paid to Close Deals, Not Update Your CRM",
  description:
    "GAIA monitors your pipeline around the clock, spots deals going cold, and drafts follow-ups before you remember to check. Your CRM stays current without you touching it.",
  alternates: {
    canonical: "/for/sales-professionals",
  },
};

export default function SalesProfessionalsPage() {
  const pageUrl = `${siteConfig.url}/sales-professionals`;
  const breadcrumbs = [
    { name: "Home", url: siteConfig.url },
    { name: "For Sales Professionals", url: pageUrl },
  ];

  return (
    <>
      <JsonLd
        data={[
          generateWebPageSchema(
            "For Sales: You're Paid to Close Deals, Not Update Your CRM",
            "GAIA monitors your pipeline around the clock, spots deals going cold, and drafts follow-ups before you remember to check. Your CRM stays current without you touching it.",
            pageUrl,
            breadcrumbs,
          ),
          generateBreadcrumbSchema(breadcrumbs),
          generateFAQSchema(SALES_FAQS),
        ]}
      />
      <SalesClient />
    </>
  );
}
