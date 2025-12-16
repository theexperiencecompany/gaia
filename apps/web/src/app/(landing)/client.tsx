"use client";

import { Suspense, useEffect } from "react";
import { LandingDownloadSection } from "@/features/download/components/DownloadPage";
import HeroImage from "@/features/landing/components/hero/HeroImage";
import HeroSection from "@/features/landing/components/hero/HeroSection";
import CommunitySection from "@/features/landing/components/sections/CommunitySection";
import FinalSection from "@/features/landing/components/sections/FinalSection";
import OpenSource from "@/features/landing/components/sections/OpenSource";
import Personalised from "@/features/landing/components/sections/Personalised";
import Productivity from "@/features/landing/components/sections/Productivity";
import ProductivityOS from "@/features/landing/components/sections/ProductivityOS";
import TestimonialsSection from "@/features/landing/components/sections/TestimonialsSection";
import TiredBoringAssistants from "@/features/landing/components/sections/TiredBoringAssistants";
import ToolsShowcaseSection from "@/features/landing/components/sections/ToolsShowcaseSection";
import WorkflowSection from "@/features/landing/components/sections/WorkflowSection";
import { FAQAccordion } from "@/features/pricing/components/FAQAccordion";

export default function LandingPageClient() {
  useEffect(() => {
    document.documentElement.style.overflowY = "scroll";

    return () => {
      document.documentElement.style.overflowY = "auto";
    };
  }, []);

  return (
    <div className="relative overflow-hidden">
      <div className="absolute inset-0 h-screen w-full">
        <HeroImage shouldHaveInitialFade />
        <div className="pointer-events-none absolute inset-x-0 -top-20 z-10 h-[30vh] bg-linear-to-b from-background to-transparent" />
        <div className="pointer-events-none absolute inset-x-0 bottom-0 z-10 h-[30vh] bg-linear-to-t from-background to-transparent" />
      </div>

      <section className="relative z-20 flex min-h-screen w-full flex-col items-center justify-center">
        <HeroSection />
      </section>

      <div>
        <div className="relative">
          <TiredBoringAssistants />

          <div
            className="absolute top-140 z-0 h-[120vh] w-screen blur-lg"
            style={{
              backgroundImage: `
              radial-gradient(circle at center, #00bbff80 0%, transparent 70%)
              `,
              opacity: 0.6,
            }}
          />
        </div>

        <ProductivityOS />

        <ToolsShowcaseSection />

        <WorkflowSection />

        <Productivity />

        <Personalised />

        <TestimonialsSection />

        <OpenSource />

        <Suspense fallback={null}>
          <FAQAccordion />
        </Suspense>

        <LandingDownloadSection />

        <CommunitySection />

        <FinalSection showSocials={false} />
      </div>
    </div>
  );
}
