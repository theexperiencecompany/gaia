"use client";

import dynamic from "next/dynamic";
import Image from "next/image";
import { useEffect, useState } from "react";
import HeroImage from "@/features/landing/components/hero/HeroImage";
import HeroSection from "@/features/landing/components/hero/HeroSection";
import LazyMotionProvider from "@/features/landing/components/LazyMotionProvider";
import {
  isDarkTimeOfDay,
  type TimeOfDay,
} from "@/features/landing/utils/timeOfDay";

const TIME_OF_DAY_CYCLE: TimeOfDay[] = ["morning", "day", "evening", "night"];

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
const WorkflowSection = dynamic(
  () => import("@/features/landing/components/sections/WorkflowSection"),
  { loading: SectionLoader },
);
const UseCasesSectionLanding = dynamic(
  () => import("@/features/landing/components/sections/Productivity"),
  { loading: SectionLoader },
);
const TodoShowcaseSection = dynamic(
  () => import("@/features/landing/components/sections/TodoShowcaseSection"),
  { loading: SectionLoader },
);
const OpenSource = dynamic(
  () => import("@/features/landing/components/sections/OpenSource"),
  { loading: SectionLoader },
);
const FAQAccordion = dynamic(
  () =>
    import("@/features/pricing/components/FAQAccordion").then((mod) => ({
      default: mod.FAQAccordion,
    })),
  { loading: SectionLoader },
);
const LandingDownloadSection = dynamic(
  () =>
    import("@/features/download/components/DownloadPage").then((mod) => ({
      default: mod.LandingDownloadSection,
    })),
  { loading: SectionLoader },
);
const CommunitySection = dynamic(
  () => import("@/features/landing/components/sections/CommunitySection"),
  { loading: SectionLoader },
);
const FinalSection = dynamic(
  () => import("@/features/landing/components/sections/FinalSection"),
  { loading: SectionLoader },
);

export default function LandingPageClient({
  initialTimeOfDay,
}: {
  initialTimeOfDay: TimeOfDay;
}) {
  const [timeOfDay, setTimeOfDay] = useState<TimeOfDay>(initialTimeOfDay);
  const [clickCount, setClickCount] = useState(0);
  const isDark = isDarkTimeOfDay(timeOfDay);

  const handleTextClick = () => {
    const next = clickCount + 1;
    setClickCount(next);
    if (next % 3 === 0) {
      setTimeOfDay((prev) => {
        const idx = TIME_OF_DAY_CYCLE.indexOf(prev);
        return TIME_OF_DAY_CYCLE[(idx + 1) % TIME_OF_DAY_CYCLE.length];
      });
    }
  };

  useEffect(() => {
    document.documentElement.style.overflowY = "scroll";

    return () => {
      document.documentElement.style.overflowY = "auto";
    };
  }, []);

  return (
    <LazyMotionProvider>
      <div className="relative overflow-hidden">
        <div className="absolute inset-0 h-screen w-full opacity-100">
          <HeroImage timeOfDay={timeOfDay} />
        </div>

        <section className="relative z-20 flex min-h-screen w-full flex-col items-center justify-center">
          <HeroSection isDark={isDark} onTextClick={handleTextClick} />
        </section>

        <section className="relative z-20 w-full py-28 sm:py-20 mb-12 sm:mb-30">
          <div className="pointer-events-none absolute inset-x-0 top-0 z-10 h-[10vh] bg-linear-to-b from-black to-transparent" />

          <Image
            src="/images/wallpapers/bands_gradient_1.webp"
            alt="Gradient background"
            width={1920}
            height={1080}
            sizes="100vw"
            style={{
              width: "100%",
              height: "100%",
              objectFit: "cover",
              position: "absolute",
              top: 0,
              left: 0,
            }}
            className="-z-10 opacity-90"
            loading="lazy"
          />
          <ChatDemoSection />
        </section>

        <div>
          <TiredBoringAssistants />
          <WorkflowSection />
          <UseCasesSectionLanding />
          <TodoShowcaseSection />
          <OpenSource />
          <FAQAccordion />
          <LandingDownloadSection />
          <CommunitySection />
          <FinalSection
            showSocials={false}
            timeOfDay={timeOfDay}
            isDark={isDark}
            onTextClick={handleTextClick}
          />
        </div>
      </div>
    </LazyMotionProvider>
  );
}
