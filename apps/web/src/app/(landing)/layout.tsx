"use client";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import Footer from "@/components/navigation/Footer";
import Navbar from "@/components/navigation/Navbar";
import BlurStack, { type BlurLayer } from "@/components/ui/blur-stack";
import LazyMotionProvider from "@/features/landing/components/LazyMotionProvider";

export default function LandingLayout({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const isDesktopLogin = pathname === "/desktop-login";

  const ORIGINAL_BLUR_CONFIG: BlurLayer[] = [
    { blur: 0.078125, maskStops: [0, 12.5, 25, 37.5], zIndex: 1 },
    { blur: 0.15625, maskStops: [12.5, 25, 37.5, 50], zIndex: 2 },
    { blur: 0.3125, maskStops: [25, 37.5, 50, 62.5], zIndex: 3 },
    { blur: 0.625, maskStops: [37.5, 50, 62.5, 75], zIndex: 4 },
    { blur: 1.25, maskStops: [50, 62.5, 75, 87.5], zIndex: 5 },
    { blur: 2.5, maskStops: [62.5, 75, 87.5, 100], zIndex: 6 },
    { blur: 5, maskStops: [75, 87.5, 100, 100], zIndex: 7 },
    { blur: 10, maskStops: [87.5, 100, 100, 100], zIndex: 8 },
  ];

  return (
    <div className="relative ">
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-9999 focus:rounded-lg focus:bg-white focus:px-4 focus:py-2 focus:text-black focus:shadow-lg"
      >
        Skip to main content
      </a>
      <div
        id="navbar-backdrop"
        className="pointer-events-none fixed inset-0 z-40 bg-black/20 opacity-0 backdrop-blur-sm transition-opacity duration-300 ease-in-out"
      />

      <BlurStack
        className="fixed h-[100px] w-screen z-1000 bottom-0 pointer-events-none"
        config={ORIGINAL_BLUR_CONFIG}
      />

      {!isDesktopLogin && <Navbar />}

      <main id="main-content" className="min-h-screen">
        <LazyMotionProvider>{children}</LazyMotionProvider>
      </main>

      {!isDesktopLogin && <Footer />}
    </div>
  );
}
