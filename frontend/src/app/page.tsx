import type { Metadata } from "next";

import LandingPageClient from "@/app/client";
import JsonLd from "@/components/seo/JsonLd";
import {
  generateOrganizationSchema,
  generatePageMetadata,
  generateWebSiteSchema,
} from "@/lib/seo";

export const metadata: Metadata = generatePageMetadata({
  title: "GAIA - General-purpose AI Assistant",
  description:
    "GAIA is your personal AI assistant designed to boost productivity. Automate tasks, manage emails, schedule meetings, track goals, and handle your daily workflow with intelligent automation.",
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
