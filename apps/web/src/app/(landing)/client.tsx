"use client";

import dynamic from "next/dynamic";
import Image from "next/image";
import { useEffect } from "react";
import HeroImage from "@/features/landing/components/hero/HeroImage";
import HeroSection from "@/features/landing/components/hero/HeroSection";
import LazyMotionProvider from "@/features/landing/components/LazyMotionProvider";

// Below-fold sections — dynamically imported to reduce initial bundle
const ChatDemoSection = dynamic(
  () => import("@/features/landing/components/demo/ChatDemoSection"),
);
const TiredBoringAssistants = dynamic(
  () => import("@/features/landing/components/sections/TiredBoringAssistants"),
);
const WorkflowSection = dynamic(
  () => import("@/features/landing/components/sections/WorkflowSection"),
);
const UseCasesSectionLanding = dynamic(
  () => import("@/features/landing/components/sections/Productivity"),
);
const TodoShowcaseSection = dynamic(
  () => import("@/features/landing/components/sections/TodoShowcaseSection"),
);
const OpenSource = dynamic(
  () => import("@/features/landing/components/sections/OpenSource"),
);
const FAQAccordion = dynamic(() =>
  import("@/features/pricing/components/FAQAccordion").then((mod) => ({
    default: mod.FAQAccordion,
  })),
);
const LandingDownloadSection = dynamic(() =>
  import("@/features/download/components/DownloadPage").then((mod) => ({
    default: mod.LandingDownloadSection,
  })),
);
const CommunitySection = dynamic(
  () => import("@/features/landing/components/sections/CommunitySection"),
);
const FinalSection = dynamic(
  () => import("@/features/landing/components/sections/FinalSection"),
);

export default function LandingPageClient() {
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
          <HeroImage />
        </div>

        <section className="relative z-20 flex min-h-screen w-full flex-col items-center justify-center">
          <HeroSection />
        </section>

        <section className="relative z-20 w-full py-20 mb-12 sm:mb-30">
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
          <FinalSection showSocials={false} />
        </div>
      </div>
    </LazyMotionProvider>
  );
}
