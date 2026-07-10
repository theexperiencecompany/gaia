"use client";

import dynamic from "next/dynamic";
import Image from "next/image";
import { useCallback, useEffect, useState } from "react";
import HeroSection from "@/features/landing/components/hero/HeroSection";
import LazyMotionProvider from "@/features/landing/components/LazyMotionProvider";
import type { LatestRelease } from "@/features/landing/utils/getLatestRelease";
import {
  getNextTimeOfDay,
  getTimeOfDay,
  isDarkTimeOfDay,
  type TimeOfDay,
} from "@/features/landing/utils/timeOfDay";
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
const TimeSavedCounter = dynamic(
  () => import("@/features/landing/components/sections/TimeSavedCounter"),
  { loading: SectionLoader, ssr: false },
);
const TiredBoringAssistants = dynamic(
  () => import("@/features/landing/components/sections/TiredBoringAssistants"),
  { loading: SectionLoader },
);
const MemoryShowcaseSection = dynamic(
  () => import("@/features/landing/components/sections/MemoryShowcaseSection"),
  { loading: SectionLoader },
);
// Superseded by the upcoming "GAIA runs your day" section (blocked on PR #854).
// const WorkflowSection = dynamic(
//   () => import("@/features/landing/components/sections/WorkflowSection"),
//   { loading: SectionLoader },
// );
const UseCasesSectionLanding = dynamic(
  () => import("@/features/landing/components/sections/Productivity"),
  { loading: SectionLoader },
);
// const TodoShowcaseSection = dynamic(
//   () => import("@/features/landing/components/sections/TodoShowcaseSection"),
//   { loading: SectionLoader },
// );
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
  initialTimeOfDay,
  latestRelease,
}: {
  initialTimeOfDay: TimeOfDay;
  latestRelease: LatestRelease | null;
}) {
  const [timeOfDay, setTimeOfDay] = useState<TimeOfDay>(initialTimeOfDay);
  const [clickCount, setClickCount] = useState(0);
  const isDark = isDarkTimeOfDay(timeOfDay);

  const handleTextClick = () => {
    const next = clickCount + 1;
    setClickCount(next);
    if (next % 3 === 0) {
      setTimeOfDay((prev) => getNextTimeOfDay(prev));
    }
  };

  const handleTimeChange = useCallback(() => {
    setTimeOfDay((prev) => getNextTimeOfDay(prev));
  }, []);

  useEffect(() => {
    const userTimezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
    setTimeOfDay(getTimeOfDay(userTimezone));
  }, []);

  useEffect(() => {
    document.documentElement.style.overflowY = "scroll";

    return () => {
      document.documentElement.style.overflowY = "auto";
    };
  }, []);

  return (
    <LazyMotionProvider>
      <div className="relative overflow-hidden">
        {/* Hero and the live demo share one section over the bands-gradient
            wallpaper — the demo IS the hero image. */}
        <section className="relative flex min-h-screen w-full flex-col items-center justify-center pb-16">
          <Image
            src="/images/wallpapers/bands_gradient_1.webp"
            alt=""
            fill
            priority
            sizes="100vw"
            className="z-0 object-cover opacity-90"
          />

          <HeroSection
            isDark
            onTextClick={handleTextClick}
            latestRelease={latestRelease}
          />
          <ChatDemoSection />
        </section>

        <TimeSavedCounter />

        <div>
          {/* Capabilities — what GAIA does */}
          <TiredBoringAssistants />

          {/* Reach — where you can use it */}
          <BotsShowcaseSection />

          {/* <WorkflowSection /> — replaced by "GAIA runs your day" post-#854 */}
          <UseCasesSectionLanding />

          {/* Memory — an assistant that actually knows you */}
          <MemoryShowcaseSection />
          {/* <TodoShowcaseSection /> — replaced by "GAIA runs your day" post-#854 */}

          <OpenSource />

          {/* Decision — price */}
          <PricingSection />

          {/* Objections + final CTA */}
          <FAQAccordion faqs={homepageFAQs} />
          <FinalSection
            showSocials={false}
            timeOfDay={timeOfDay}
            isDark={isDark}
            onTextClick={handleTextClick}
            onTimeChange={handleTimeChange}
          />
        </div>
      </div>
    </LazyMotionProvider>
  );
}
