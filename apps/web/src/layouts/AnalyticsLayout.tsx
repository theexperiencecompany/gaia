"use client";

import { GoogleAnalytics } from "@next/third-parties/google";
import dynamic from "next/dynamic";
import { useEffect, useState } from "react";

// Lazy-load Vercel's own Analytics + Speed Insights so they don't ship on the
// critical path. Same deferred pattern as Google Analytics below.
const VercelAnalytics = dynamic(
  () =>
    import("@vercel/analytics/next").then((m) => ({ default: m.Analytics })),
  { ssr: false },
);
const SpeedInsights = dynamic(
  () =>
    import("@vercel/speed-insights/next").then((m) => ({
      default: m.SpeedInsights,
    })),
  { ssr: false },
);

// Use NEXT_PUBLIC_GA_ID from environment variables
const GA_ID = process.env.NEXT_PUBLIC_GA_ID;

export default function AnalyticsLayout() {
  const [shouldLoad, setShouldLoad] = useState(false);

  useEffect(() => {
    const timer = setTimeout(() => {
      setShouldLoad(true);
    }, 2000);

    return () => clearTimeout(timer);
  }, []);

  if (!shouldLoad) return null;

  return (
    <>
      {GA_ID ? <GoogleAnalytics gaId={GA_ID} /> : null}
      <VercelAnalytics />
      <SpeedInsights />
    </>
  );
}
