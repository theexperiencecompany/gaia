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
import ImageSelector from "@/features/landing/components/shared/ImageSelector";
import { FAQAccordion } from "@/features/pricing/components/FAQAccordion";

export default function LandingPageClient() {
  useEffect(() => {
    document.documentElement.style.overflowY = "scroll";

    return () => {
      document.documentElement.style.overflowY = "auto";
    };
  }, []);

  const imageOptions = [
    {
      name: "Calendar",
      src: "/images/screenshots/calendar.webp",
    },
    {
      name: "Chats",
      src: "/images/screenshots/chats.png",
    },
    {
      name: "Todos",
      src: "/images/screenshots/todos.webp",
    },
    {
      name: "Goals",
      src: "/images/screenshots/goals.png",
    },
    {
      name: "Mail",
      src: "/images/screenshots/mail.webp",
    },
  ];
  return (
    <div className="relative overflow-hidden">
      <div className="absolute inset-0 h-screen w-full opacity-80">
        <HeroImage />
      </div>

      <section className="relative z-20 flex min-h-screen w-full flex-col items-center justify-center">
        <HeroSection />
      </section>

      <div className="mx-auto max-w-6xl relative -top-25 z-20">
        <ImageSelector images={imageOptions} defaultIndex={2} />
      </div>

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
        <FAQAccordion />
        <LandingDownloadSection />
        <CommunitySection />
        <FinalSection showSocials={false} />
      </div>
    </div>
  );
}
