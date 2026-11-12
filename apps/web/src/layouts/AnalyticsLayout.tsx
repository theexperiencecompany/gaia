"use client";

import Script from "next/script";
import { useEffect, useState } from "react";
import { onFirstInteraction } from "@/lib/firstInteraction";
import { FASTLANE_HOST, RYBBIT_HOST } from "../../third-party-origins.mjs";

const RYBBIT_SITE_ID = process.env.NEXT_PUBLIC_RYBBIT_SITE_ID;
const FASTLANE_TRACKING_ID = process.env.NEXT_PUBLIC_FASTLANE_TRACKING_ID;
const FASTLANE_DELAY_MS = 2000;

/** Fastlane two seconds after mount; Rybbit (analytics + session replay) on the visitor's first interaction. */
export default function AnalyticsLayout() {
  const [loadFastlane, setLoadFastlane] = useState(false);
  const [loadRybbit, setLoadRybbit] = useState(false);

  useEffect(() => {
    const timer = setTimeout(() => setLoadFastlane(true), FASTLANE_DELAY_MS);
    return () => clearTimeout(timer);
  }, []);

  useEffect(() => onFirstInteraction(() => setLoadRybbit(true)), []);

  return (
    <>
      {RYBBIT_SITE_ID && loadRybbit ? (
        <Script
          src={`${RYBBIT_HOST}/api/script.js`}
          data-site-id={RYBBIT_SITE_ID}
          strategy="afterInteractive"
        />
      ) : null}
      {FASTLANE_TRACKING_ID && loadFastlane ? (
        <Script
          id="fastlane"
          src={`${FASTLANE_HOST}/api/a/${FASTLANE_TRACKING_ID}`}
          strategy="afterInteractive"
        />
      ) : null}
    </>
  );
}
