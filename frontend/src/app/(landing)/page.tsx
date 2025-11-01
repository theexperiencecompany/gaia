import type { Metadata } from "next";

import LandingPageClient from "@/app/(landing)/client";
import JsonLd from "@/components/seo/JsonLd";
import {
  generateOrganizationSchema,
  generatePageMetadata,
  generateWebSiteSchema,
} from "@/lib/seo";

export const metadata: Metadata = generatePageMetadata({
  title: "GAIA",
  path: "/",
  keywords: [
    "personal AI assistant",
    "productivity tool",
    "task automation",
    "email management",
    "meeting scheduler",
    "AI productivity",
    "workflow automation",
    "smart assistant",
    "digital assistant",
    "AI task manager",
  ],
});

export default function LandingPage() {
  const organizationSchema = generateOrganizationSchema();
  const websiteSchema = generateWebSiteSchema();

  return (
    <>
      <JsonLd data={[organizationSchema, websiteSchema]} />
      <LandingPageClient />
    </>
  );
}
