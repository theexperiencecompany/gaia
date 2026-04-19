import type { Metadata } from "next";

import LandingPageClient from "@/app/[locale]/(landing)/client";
import JsonLd from "@/components/seo/JsonLd";
import {
  getTimeOfDay,
  type TimeOfDay,
} from "@/features/landing/utils/timeOfDay";
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

// Preload paths mirror WALLPAPERS in HeroImage.tsx — keep in sync.
const HERO_WALLPAPER_PATHS: Record<TimeOfDay, string> = {
  morning: "/images/wallpapers/swiss_morning.webp",
  day: "/images/wallpapers/swiss.webp",
  evening: "/images/wallpapers/swiss_evening.webp",
  night: "/images/wallpapers/swiss_night.webp",
};

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
      {/* Preload the initial hero wallpaper so it starts fetching before JS runs.
          HeroImage renders inside a "use client" component, so Next.js may not
          emit a preload link via the Image component's SSR path. */}
      <link
        rel="preload"
        as="image"
        href={HERO_WALLPAPER_PATHS[initialTimeOfDay]}
        fetchPriority="high"
      />
      <JsonLd
        data={[
          organizationSchema,
          websiteSchema,
          webPageSchema,
          breadcrumbSchema,
          faqSchema,
        ]}
      />
      <LandingPageClient initialTimeOfDay={initialTimeOfDay} />
    </>
  );
}
