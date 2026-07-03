import type { Metadata } from "next";

import LandingPageClient from "@/app/[locale]/(landing)/client";
import JsonLd from "@/components/seo/JsonLd";
import { getLatestRelease } from "@/features/landing/utils/getLatestRelease";
import { getTimeOfDay } from "@/features/landing/utils/timeOfDay";
import { homepageFAQs } from "@/lib/page-faqs";
import {
  generateBreadcrumbSchema,
  generateFAQSchema,
  generateOrganizationSchema,
  generatePageMetadata,
  generateWebPageSchema,
  generateWebSiteSchema,
  siteConfig,
} from "@/lib/seo";

// ISR: give the homepage a stable incremental-cache entry so OpenNext's cache
// interception serves it without booting the full Next server (the worker
// cold-start path). Also refreshes the time-of-day seed hourly instead of
// freezing it at build time.
export const revalidate = 3600;

export const metadata: Metadata = generatePageMetadata({
  title: siteConfig.name,
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
  const initialTimeOfDay = getTimeOfDay();
  const latestRelease = getLatestRelease();
  const organizationSchema = generateOrganizationSchema();
  const websiteSchema = generateWebSiteSchema();
  const webPageSchema = generateWebPageSchema(
    siteConfig.name,
    siteConfig.description,
    siteConfig.url,
  );

  const breadcrumbSchema = generateBreadcrumbSchema([
    { name: "Home", url: siteConfig.url },
  ]);
  const faqSchema = generateFAQSchema(homepageFAQs);

  return (
    <>
      {/* The hero wallpaper preload is emitted automatically by next/image's
          `priority` prop (verified in the rendered HTML), so no manual <link
          rel="preload"> is needed — a manual one points at the raw asset URL,
          not the optimized /_next/image URL the component actually fetches, so
          it just wastes bandwidth on the LCP path. */}
      <JsonLd
        data={[
          organizationSchema,
          websiteSchema,
          webPageSchema,
          breadcrumbSchema,
          faqSchema,
        ]}
      />
      <LandingPageClient
        initialTimeOfDay={initialTimeOfDay}
        latestRelease={latestRelease}
      />
    </>
  );
}
