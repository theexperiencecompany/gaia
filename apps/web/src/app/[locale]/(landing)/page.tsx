import "../../styles/marketing.css";
import type { Metadata } from "next";

import LandingPageClient from "@/app/[locale]/(landing)/client";
import JsonLd from "@/components/seo/JsonLd";
import { getLatestRelease } from "@/features/landing/utils/getLatestRelease";
import { WorkflowIconElementsProvider } from "@/features/workflows/components/shared/WorkflowIconElements";
import { EXPLORE_WORKFLOWS_LIMIT } from "@/features/workflows/constants/explore";
import { getExploreWorkflowsServer } from "@/features/workflows/lib/serverWorkflowsApi";
import { workflowIconElements } from "@/features/workflows/lib/workflowIconElements";
import { homepageFAQs } from "@/lib/faq";
import {
  generateBreadcrumbSchema,
  generateFAQSchema,
  generatePageMetadata,
  generateProductSchema,
  generateWebPageSchema,
  siteConfig,
} from "@/lib/seo";

// ISR: gives the homepage a stable incremental-cache entry so OpenNext's
// cache interception serves it without a full Next server cold-start, and
// refreshes the time-of-day seed hourly instead of freezing it at build time.
export const revalidate = 3600;

export const metadata: Metadata = generatePageMetadata({
  title: siteConfig.name,
  description:
    "GAIA is the proactive personal AI assistant that triages your email, plans your calendar, and runs your workflows, right inside WhatsApp and Telegram.",
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

export default async function LandingPage() {
  const latestRelease = getLatestRelease();
  const webPageSchema = generateWebPageSchema(
    siteConfig.name,
    siteConfig.description,
    siteConfig.url,
  );

  const breadcrumbSchema = generateBreadcrumbSchema([
    { name: "Home", url: siteConfig.url },
  ]);
  const faqSchema = generateFAQSchema(homepageFAQs);
  const exploreWorkflows = await getExploreWorkflowsServer(
    EXPLORE_WORKFLOWS_LIMIT,
  );

  return (
    <>
      {/* The hero wallpaper preload is emitted automatically by next/image's
          `priority` prop (verified in the rendered HTML), so no manual <link
          rel="preload"> is needed — a manual one points at the raw asset URL,
          not the optimized /_next/image URL the component actually fetches, so
          it just wastes bandwidth on the LCP path. */}
      <JsonLd
        data={[
          webPageSchema,
          breadcrumbSchema,
          faqSchema,
          generateProductSchema(),
        ]}
      />
      <WorkflowIconElementsProvider
        icons={workflowIconElements(exploreWorkflows)}
      >
        <LandingPageClient latestRelease={latestRelease} />
      </WorkflowIconElementsProvider>
    </>
  );
}
