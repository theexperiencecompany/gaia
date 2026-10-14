"use client";

import { GoogleAnalytics } from "@next/third-parties/google";
import Script from "next/script";
import { useEffect, useState } from "react";

const GA_ID = process.env.NEXT_PUBLIC_GA_ID;
const RYBBIT_SITE_ID = process.env.NEXT_PUBLIC_RYBBIT_SITE_ID;
const RYBBIT_HOST =
  process.env.NEXT_PUBLIC_RYBBIT_HOST ?? "https://as.heygaia.io";
const FASTLANE_TRACKING_ID = process.env.NEXT_PUBLIC_FASTLANE_TRACKING_ID;
const FASTLANE_HOST =
  process.env.NEXT_PUBLIC_FASTLANE_HOST ??
  "https://aromatic-caribou-889.convex.site";

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
      {RYBBIT_SITE_ID ? (
        <Script
          src={`${RYBBIT_HOST}/api/script.js`}
          data-site-id={RYBBIT_SITE_ID}
          strategy="afterInteractive"
        />
      ) : null}
      {FASTLANE_TRACKING_ID ? (
        <Script
          id="fastlane"
          src={`${FASTLANE_HOST}/api/a/${FASTLANE_TRACKING_ID}`}
          strategy="afterInteractive"
        />
      ) : null}
      {GA_ID ? <GoogleAnalytics gaId={GA_ID} /> : null}
    </>
  );
}
