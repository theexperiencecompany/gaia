import type { Metadata } from "next";
import JsonLd from "@/components/seo/JsonLd";
import { PM_FAQS } from "@/features/landing/data/personaFaqs";
import {
  generateBreadcrumbSchema,
  generateFAQSchema,
  generateWebPageSchema,
  siteConfig,
} from "@/lib/seo";
import ProductManagerClient from "./ProductManagerClient";

export const metadata: Metadata = {
  title:
    "GAIA for Product Managers: Stop Managing Tools, Start Managing Your Product",
  description:
    "GAIA connects Linear, Slack, GitHub, and Notion, then handles the status updates, meeting prep, and feature triage so you can focus on product strategy.",
  alternates: {
    canonical: "/for/product-managers",
  },
};

export default function ProductManagersPage() {
  const pageUrl = `${siteConfig.url}/product-managers`;
  const breadcrumbs = [
    { name: "Home", url: siteConfig.url },
    { name: "For Product Managers", url: pageUrl },
  ];

  return (
    <>
      <JsonLd
        data={[
          generateWebPageSchema(
            "GAIA for Product Managers: Stop Managing Tools, Start Managing Your Product",
            "GAIA connects Linear, Slack, GitHub, and Notion, then handles the status updates, meeting prep, and feature triage so you can focus on product strategy.",
            pageUrl,
            breadcrumbs,
          ),
          generateBreadcrumbSchema(breadcrumbs),
          generateFAQSchema(PM_FAQS),
        ]}
      />
      <ProductManagerClient />
    </>
  );
}
