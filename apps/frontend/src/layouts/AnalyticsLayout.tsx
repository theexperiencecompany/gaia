"use client";

import { GoogleAnalytics } from "@next/third-parties/google";
import { useEffect, useState } from "react";

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

  return shouldLoad && GA_ID ? <GoogleAnalytics gaId={GA_ID} /> : null;
}
