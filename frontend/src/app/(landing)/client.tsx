"use client";

import NextImage from "next/image";
import { lazy, Suspense, useEffect, useState } from "react";

import SuspenseLoader from "@/components/shared/SuspenseLoader";
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

  const [loaded, setLoaded] = useState(false);
  const [initialloaded, setInitialLoaded] = useState(false);

  return (
    // <ReactLenis root>
    <div className="relative overflow-hidden">
      <div className="absolute inset-0 h-screen w-full">
        <div className="relative h-full w-full">
          {/* Base WEBP visible immediately */}
          <NextImage
            src="/images/wallpapers/g3.webp"
            alt="wallpaper webp"
            fill
            priority
            sizes="100vw"
            onLoadingComplete={() => setInitialLoaded(true)}
            className={`object-cover duration-200 ${initialloaded ? "opacity-100" : "opacity-0"} transition`}
          />

          {/* PNG fades in later */}
          <NextImage
            src="/images/wallpapers/g3.png"
            alt="wallpaper png"
            fill
            sizes="100vw"
            onLoadingComplete={() => setLoaded(true)}
            className={`object-cover transition-opacity ${loaded ? "opacity-100" : "opacity-0"}`}
          />
        </div>
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
          <Suspense fallback={<SuspenseLoader />}>
            <Tired />
          </Suspense>

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

        <Suspense fallback={<SuspenseLoader />}>
          <ProductivityOS />
        </Suspense>

        <Suspense fallback={<SuspenseLoader />}>
          <AllYourTools />
        </Suspense>

        <Suspense fallback={<SuspenseLoader />}>
          <WorkflowSection />
        </Suspense>

        <Suspense fallback={<SuspenseLoader />}>
          <AutomateDailyChaos />
        </Suspense>

        <Suspense fallback={<SuspenseLoader />}>
          <Personalised />
        </Suspense>

        <Suspense fallback={<SuspenseLoader />}>
          <TestimonialsSection />
        </Suspense>

        <Suspense fallback={<SuspenseLoader />}>
          <OpenSource />
        </Suspense>

        <Suspense fallback={<SuspenseLoader />}>
          <FAQAccordion />
        </Suspense>

        <Suspense fallback={<SuspenseLoader />}>
          <CommunitySection />
        </Suspense>

        <Suspense fallback={<SuspenseLoader />}>
          <FinalSection showSocials={false} />
        </Suspense>
      </div>
    </div>
    // </ReactLenis>
  );
}
