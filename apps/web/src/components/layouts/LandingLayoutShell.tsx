"use client";
import dynamic from "next/dynamic";
import type { ReactNode } from "react";
import Navbar from "@/components/navigation/Navbar";
import {
  MAIN_CONTENT_ID,
  SkipToContentLink,
} from "@/components/navigation/SkipToContentLink";
import BlurStack, { type BlurLayer } from "@/components/ui/blur-stack";
import LazyMotionProvider from "@/features/landing/components/LazyMotionProvider";
import { usePathname } from "@/i18n/navigation";
import LandingProvidersLayout from "@/layouts/LandingProvidersLayout";
import { showsMarketingChrome } from "./marketingChrome";

// Footer is always below the fold on landing pages — defer it so it doesn't
// compete with hero-above-the-fold rendering for main-thread time.
const Footer = dynamic(() => import("@/components/navigation/Footer"), {
  ssr: true,
  loading: () => null,
});

const BLUR_CONFIG: BlurLayer[] = [
  { blur: 0.078125, maskStops: [0, 12.5, 25, 37.5], zIndex: 1 },
  { blur: 0.15625, maskStops: [12.5, 25, 37.5, 50], zIndex: 2 },
  { blur: 0.3125, maskStops: [25, 37.5, 50, 62.5], zIndex: 3 },
  { blur: 0.625, maskStops: [37.5, 50, 62.5, 75], zIndex: 4 },
  { blur: 1.25, maskStops: [50, 62.5, 75, 87.5], zIndex: 5 },
  { blur: 2.5, maskStops: [62.5, 75, 87.5, 100], zIndex: 6 },
  { blur: 5, maskStops: [75, 87.5, 100, 100], zIndex: 7 },
  { blur: 10, maskStops: [87.5, 100, 100, 100], zIndex: 8 },
];

export default function LandingLayoutShell({
  children,
  selfhost,
}: {
  children: ReactNode;
  /** Whether this web server fronts a self-hosted instance. */
  selfhost: boolean;
}) {
  const pathname = usePathname();
  const chrome = showsMarketingChrome(pathname, selfhost);

  return (
    <LandingProvidersLayout>
      <div className="relative ">
        <SkipToContentLink />
        <div
          id="navbar-backdrop"
          className="pointer-events-none fixed inset-0 z-40 bg-black/20 opacity-0 backdrop-blur-sm transition-opacity duration-300 ease-in-out"
        />

        <BlurStack
          className="fixed h-[100px] w-screen z-10 bottom-0 pointer-events-none"
          config={BLUR_CONFIG}
        />

        <LazyMotionProvider>
          {chrome && <Navbar />}

          <main id={MAIN_CONTENT_ID} className="min-h-screen">
            {children}
          </main>
        </LazyMotionProvider>

        {chrome && <Footer />}
      </div>
    </LandingProvidersLayout>
  );
}
