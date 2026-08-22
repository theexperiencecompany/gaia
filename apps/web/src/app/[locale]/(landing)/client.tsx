"use client";

import dynamic from "next/dynamic";
import Image from "next/image";
import { useEffect } from "react";
import ProgressiveImage from "@/components/ui/ProgressiveImage";
import HeroSection from "@/features/landing/components/hero/HeroSection";
import LazyMotionProvider from "@/features/landing/components/LazyMotionProvider";
import type { LatestRelease } from "@/features/landing/utils/getLatestRelease";
import { homepageFAQs } from "@/lib/faq";

function SectionLoader() {
  return (
    <div className="w-full animate-pulse py-20">
      <div className="mx-auto max-w-4xl space-y-4 px-6">
        <div className="h-8 w-1/3 rounded-lg bg-white/10" />
        <div className="h-4 w-2/3 rounded bg-white/10" />
        <div className="h-4 w-1/2 rounded bg-white/10" />
      </div>
    </div>
  );
}

// Below-fold sections — dynamically imported to reduce initial bundle
const ChatDemoSection = dynamic(
  () => import("@/features/landing/components/demo/ChatDemoSection"),
  { loading: SectionLoader },
);
const TiredBoringAssistants = dynamic(
  () => import("@/features/landing/components/sections/TiredBoringAssistants"),
  { loading: SectionLoader },
);
const RunsYourDaySection = dynamic(
  () => import("@/features/landing/components/sections/RunsYourDaySection"),
  { loading: SectionLoader },
);
const WorkflowsSection = dynamic(
  () => import("@/features/landing/components/sections/WorkflowsSection"),
  { loading: SectionLoader },
);
const MemorySection = dynamic(
  () => import("@/features/landing/components/sections/MemorySection"),
  { loading: SectionLoader },
);
const UseCasesSectionLanding = dynamic(
  () => import("@/features/landing/components/sections/Productivity"),
  { loading: SectionLoader },
);
const BotsShowcaseSection = dynamic(
  () => import("@/features/landing/components/sections/BotsShowcaseSection"),
  { loading: SectionLoader },
);
const OpenSource = dynamic(
  () => import("@/features/landing/components/sections/OpenSource"),
  { loading: SectionLoader },
);
const PricingSection = dynamic(
  () => import("@/features/landing/components/sections/PricingSection"),
  { loading: SectionLoader },
);
const FAQAccordion = dynamic(
  () =>
    import("@/features/pricing/components/FAQAccordion").then((mod) => ({
      default: mod.FAQAccordion,
    })),
  { loading: SectionLoader },
);
const FinalSection = dynamic(
  () => import("@/features/landing/components/sections/FinalSection"),
  { loading: SectionLoader },
);

export default function LandingPageClient({
  latestRelease,
}: {
  latestRelease: LatestRelease | null;
}) {
  useEffect(() => {
    document.documentElement.style.overflowY = "scroll";

    return () => {
      document.documentElement.style.overflowY = "auto";
    };
  }, []);

  return (
    <LazyMotionProvider>
      <div className="relative overflow-hidden">
        {/* Hero — alpine-valley wallpaper behind the headline */}
        <section className="relative flex min-h-screen w-full flex-col items-center justify-center">
          <div className="absolute inset-0 z-0 h-full w-full">
            {/* Webp loads first for the LCP; the higher-quality PNG then
                fades in on top (lazy + low priority, never blocks the LCP). */}
            <ProgressiveImage
              webpSrc="/images/wallpapers/ethereal_alpine_valley.webp"
              pngSrc="/images/wallpapers/ethereal_alpine_valley.png"
              alt="Hero wallpaper"
              priority
              sizes="100vw"
            />
          </div>
          <div className="pointer-events-none absolute inset-0 z-0 bg-black/0" />
          {/* Top fade under the fixed navbar so nav text stays legible
              over the bright sky */}
          <div className="pointer-events-none absolute inset-x-0 top-0 z-0 h-[20vh] bg-linear-to-b from-black/70 to-transparent" />
          {/* Bottom fade into the demo section below */}
          <div className="pointer-events-none absolute inset-x-0 bottom-0 z-0 h-[20vh] bg-linear-to-t from-black to-transparent" />

          <HeroSection isDark latestRelease={latestRelease} />
        </section>

        {/* Live demo — its own section over the bands-gradient wallpaper */}
        <section className="relative z-20 w-full py-16 sm:py-12 mb-12 sm:mb-16">
          <div className="pointer-events-none absolute inset-x-0 top-0 z-10 h-[10vh] bg-linear-to-b from-black to-transparent" />
          <Image
            src="/images/wallpapers/bands_gradient_1.webp"
            alt=""
            fill
            sizes="100vw"
            className="z-0 object-cover"
          />
          <div className="relative z-10">
            <ChatDemoSection />
          </div>
        </section>

        <div>
          {/* The core promise — GAIA runs your day, told in the chats you use */}
          <RunsYourDaySection />

          {/* Capabilities — what GAIA does */}
          <TiredBoringAssistants />

          {/* The mechanism — schedules and triggers, told in a text thread */}
          <WorkflowsSection />

          {/* Depth — it knows you, not just your tools */}
          <MemorySection />

          {/* Reach — where you can use it */}
          <BotsShowcaseSection />

          <UseCasesSectionLanding />

          <OpenSource />

          {/* Decision — price */}
          <PricingSection />

          {/* Objections + final CTA */}
          <FAQAccordion faqs={homepageFAQs} />
          <FinalSection showSocials={false} />
        </div>
      </div>
    </LazyMotionProvider>
  );
}
