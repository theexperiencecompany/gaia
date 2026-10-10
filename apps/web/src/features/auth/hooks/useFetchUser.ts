"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { RedirectType, redirect, useSearchParams } from "next/navigation";
import { useEffect, useRef } from "react";
import { PUBLIC_PAGES, SESSION_RESUMED_KEY } from "@/features/auth/constants";
import {
  clearCurrentUser,
  currentUserQueryOptions,
} from "@/features/auth/hooks/useCurrentUser";
import { readPendingCheckout } from "@/features/pricing/lib/pendingCheckout";
import { usePathname } from "@/i18n/navigation";
import {
  ANALYTICS_EVENTS,
  identifyUser,
  resetUser,
  trackEvent,
} from "@/lib/analytics";

// Exactly-once guard for the OAuth login analytics event — module scope so it
// can be flipped during the render-phase redirect without writing a ref.
let hasTrackedOAuthLogin = false;

const useFetchUser = () => {
  const queryClient = useQueryClient();
  const searchParams = useSearchParams();
  const currentPath = usePathname();
  const hasIdentified = useRef(false);
  const hasClearedOnError = useRef(false);

  // The one place the current-user query is driven — the cache *is* the
  // state, nothing is copied out. Persisted for instant paint, so this
  // driver always re-validates on mount (one round-trip/load); others stay fresh-only.
  const { data, error } = useQuery({
    ...currentUserQueryOptions,
    refetchOnMount: "always",
  });

  useEffect(() => {
    if (!data) return;

    // Identify the persisted client session with the stable backend user ID.
    if (data.user_id && !hasIdentified.current) {
      identifyUser(data.user_id, {
        email: data.email ?? undefined,
        name: data.name ?? undefined,
        timezone: data.timezone ?? undefined,
        onboarding_completed: data.onboarding?.completed ?? false,
      });
      hasIdentified.current = true;
    }
  }, [data]);

  // Track session resume once, independent from store-syncing.
  useEffect(() => {
    if (!data) return;

    const isAuthRedirectPage = currentPath === "/redirect";
    const hasTrackedSessionResumed =
      sessionStorage.getItem(SESSION_RESUMED_KEY);

    if (!isAuthRedirectPage && !hasTrackedSessionResumed) {
      trackEvent(ANALYTICS_EVENTS.USER_SESSION_RESUMED, {
        method: "wos_session_cookie",
        has_completed_onboarding: data.onboarding?.completed ?? false,
      });
      sessionStorage.setItem(SESSION_RESUMED_KEY, "true");
    }
  }, [data, currentPath]);

  // OAuth redirect routing, isolated from store syncing so route changes
  // don't overwrite state with stale data. Resolved during render, not an
  // effect, so the callback page never paints before redirecting; same as router.push.
  const accessToken = searchParams.get("access_token");
  const refreshToken = searchParams.get("refresh_token");

  // OAuth redirect resolved during render (not an effect) so the callback page
  // never paints before redirecting. Login analytics are server-side only
  // (track_login on the OAuth callback); emitting here would double-count.
  if (
    data &&
    accessToken &&
    refreshToken &&
    !readPendingCheckout() &&
    !hasTrackedOAuthLogin
  ) {
    hasTrackedOAuthLogin = true;

    // A pending checkout takes priority; useCheckoutResume redirects to Dodo.
    const needsOnboarding = !data.onboarding?.completed;

    if (needsOnboarding && currentPath !== "/onboarding") {
      redirect("/onboarding", RedirectType.replace);
    }

    if (
      !needsOnboarding &&
      (currentPath === "/onboarding" || PUBLIC_PAGES.includes(currentPath))
    ) {
      redirect("/c", RedirectType.replace);
    }
  }

  // Clear user state on auth failure, dropping it from the persisted cache too.
  // Guarded by a ref: removing the query makes this observer refetch, so an
  // unguarded effect would remove it again on the next failure, in a loop.
  useEffect(() => {
    if (!error || hasClearedOnError.current) return;
    hasClearedOnError.current = true;
    console.error("Error fetching user info:", error);
    clearCurrentUser(queryClient);
    resetUser();
    hasIdentified.current = false;
  }, [error, queryClient]);
};

export default useFetchUser;
