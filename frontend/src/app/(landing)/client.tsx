"use client";

import { lazy, useEffect } from "react";
import { AnimatedLazySection } from "@/components/shared/AnimatedSection";

import HeroImage from "@/features/landing/components/hero/HeroImage";
import HeroSection from "@/features/landing/components/hero/HeroSection";
import CommunitySection from "@/features/landing/components/sections/CommunitySection";
import ProductivityOS from "@/features/landing/components/sections/ProductivityOS";
import WorkflowSection from "@/features/landing/components/sections/WorkflowSection";

const AllYourTools = lazy(
  () => import("@/features/landing/components/sections/ToolsShowcaseSection"),
);

const AutomateDailyChaos = lazy(
  () => import("@/features/landing/components/sections/Productivity"),
);

const Tired = lazy(
  () => import("@/features/landing/components/sections/TiredBoringAssistants"),
);

const Personalised = lazy(
  () => import("@/features/landing/components/sections/Personalised"),
);

const TestimonialsSection = lazy(
  () => import("@/features/landing/components/sections/TestimonialsSection"),
);

const FAQAccordion = lazy(() =>
  import("@/features/pricing/components/FAQAccordion").then((module) => ({
    default: module.FAQAccordion,
  })),
);

const OpenSource = lazy(
  () => import("@/features/landing/components/sections/OpenSource"),
);

const FinalSection = lazy(
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
    // <ReactLenis root>
    <div className="relative overflow-hidden">
      <div className="absolute inset-0 h-screen w-full">
        <HeroImage shouldHaveInitialFade />
        <div className="pointer-events-none absolute inset-x-0 -top-20 z-10 h-[30vh] bg-gradient-to-b from-background to-transparent" />
        <div className="pointer-events-none absolute inset-x-0 bottom-0 z-10 h-[30vh] bg-gradient-to-t from-background to-transparent" />
      </div>

      <section className="relative z-20 flex min-h-screen w-full flex-col items-center justify-center">
        <HeroSection />
        {/* <div className="mx-auto mt-8 flex w-full max-w-screen-xl items-center justify-center px-4 sm:px-6">
          <HeroVideoDialog
            className="block w-full rounded-3xl"
            animationStyle="from-center"
            videoSrc="https://www.youtube.com/embed/K-ZbxMHxReM?si=U9Caazt9Ondagnr8"
            thumbnailSrc="https://img.youtube.com/vi/K-ZbxMHxReM/maxresdefault.jpg"
            thumbnailAlt="Hero Section Video"
          />
        </div> */}
      </section>
      <div>
        <div className="relative">
          <AnimatedLazySection component={Tired} delay={0.1} />

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

        <AnimatedLazySection component={ProductivityOS} delay={0.2} />

        <AnimatedLazySection component={AllYourTools} delay={0.2} />

        <AnimatedLazySection component={WorkflowSection} delay={0.2} />

        <AnimatedLazySection component={AutomateDailyChaos} delay={0.2} />

        <AnimatedLazySection component={Personalised} delay={0.2} />

        <AnimatedLazySection component={TestimonialsSection} delay={0.2} />

        <AnimatedLazySection component={OpenSource} delay={0.2} />

        <AnimatedLazySection component={FAQAccordion} delay={0.2} />

        <AnimatedLazySection component={CommunitySection} delay={0.2} />

        <AnimatedLazySection
          component={FinalSection}
          componentProps={{ showSocials: false }}
          delay={0.2}
        />
      </div>
    </div>
    // </ReactLenis>
  );
}
