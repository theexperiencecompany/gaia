"use client";

import { ReactLenis } from "lenis/react";
import Image from "next/image";
import { lazy, Suspense, useEffect } from "react";

import SuspenseLoader from "@/components/shared/SuspenseLoader";
import HeroVideoDialog from "@/components/ui/magic-ui/hero-video-dialog";
import HeroSection from "@/features/landing/components/hero/HeroSection";
import CommunitySection from "@/features/landing/components/sections/CommunitySection";
import WorkflowSection from "@/features/landing/components/sections/WorkflowSection";

import LandingLayout from "./(landing)/layout";

// const ChaoticWorkspaceSection = lazy(
//   () =>
//     import("@/features/landing/components/sections/ChaoticWorkspaceSection"),
// );

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

export default function LandingPage() {
  useEffect(() => {
    document.documentElement.style.overflowY = "scroll";

    return () => {
      document.documentElement.style.overflowY = "auto";
    };
  }, []);

  return (
    <ReactLenis root>
      <LandingLayout>
        <div className="relative overflow-hidden">
          <div className="absolute inset-0 h-screen w-full">
            <Image
              src={"/images/wallpapers/switzerland_night.webp"}
              alt="GAIA Hero Section Wallpaper"
              sizes="100vw"
              priority
              fill
              className="aspect-video object-cover opacity-90"
            />
            <div className="pointer-events-none absolute inset-x-0 top-0 z-10 h-[30vh] bg-gradient-to-b from-background to-transparent" />
            <div className="pointer-events-none absolute inset-x-0 bottom-0 z-10 h-[20vh] bg-gradient-to-t from-background via-background to-transparent" />
          </div>

          <section className="relative z-20 flex min-h-screen w-full flex-col items-center justify-center">
            <HeroSection />
            <div className="mx-auto mt-8 flex w-full max-w-screen-xl items-center justify-center px-4 sm:px-6">
              <HeroVideoDialog
                className="block w-full rounded-3xl"
                animationStyle="from-center"
                videoSrc="https://www.youtube.com/embed/K-ZbxMHxReM?si=U9Caazt9Ondagnr8"
                thumbnailSrc="https://img.youtube.com/vi/K-ZbxMHxReM/maxresdefault.jpg"
                // thumbnailSrc="/images/switsze.webp?q=80"
                thumbnailAlt="Hero Section Video"
              />
            </div>
          </section>
          <div>
            <div className="relative">
              <Suspense fallback={<SuspenseLoader />}>
                <Tired />
              </Suspense>

              {/* <Suspense fallback={<SuspenseLoader />}>
              <ChaoticWorkspaceSection />
              </Suspense> */}

              <div
                className="absolute top-140 z-0 h-[120vh] w-screen blur-lg"
                style={{
                  backgroundImage: `
                      radial-gradient(circle at center, #00bbff80 0%, transparent 70%)
                    `,
                  opacity: 0.6,
                }}
              />

              <Suspense fallback={<SuspenseLoader />}>
                <AllYourTools />
              </Suspense>
            </div>

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

        {/* <div className="fixed right-6 bottom-6 z-50">
          <a
            href="https://www.producthunt.com/products/gaia-8010ee43-bc6e-40ef-989c-02c950a5b778?embed=true&utm_source=badge-featured&utm_medium=badge&utm_source=badge-gaia-6"
            target="_blank"
            rel="noopener noreferrer"
            className="block transition-transform"
          >
            <Image
              src="https://api.producthunt.com/widgets/embed-image/v1/featured.svg?post_id=1000528&theme=light&t=1754093183881"
              alt="GAIA - Proactive, Personal AI Assistant to boost your productivity | Product Hunt"
              width={250}
              height={54}
              className="drop-shadow-lg"
            />
          </a>
        </div> */}
      </LandingLayout>
    </ReactLenis>
  );
}
