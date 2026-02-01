"use client";

import { usePathname, useSearchParams } from "next/navigation";
import { useEffect, useRef } from "react";
import { posthog } from "posthog-js";

/**
 * PostHog analytics provider component.
 * Handles automatic page view tracking on route changes.
 */
export default function PostHogPageView() {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const previousPath = useRef<string | null>(null);

  useEffect(() => {
    if (!pathname) return;

    // Build the full URL for tracking
    const url = searchParams.toString() ? `${pathname}?${searchParams.toString()}` : pathname;

    // Only track if the path actually changed (avoid duplicate tracking)
    if (previousPath.current !== url) {
      posthog.capture("$pageview", {
        $current_url: url,
        path: pathname,
        referrer: typeof document !== "undefined" ? document.referrer : undefined,
      });
      previousPath.current = url;
    }
  }, [pathname, searchParams]);

  return null;
}
