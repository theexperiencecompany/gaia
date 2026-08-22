"use client";

import { useQuery } from "@tanstack/react-query";
import { RedirectType, redirect, useSearchParams } from "next/navigation";
import { useEffect, useRef } from "react";
import { authApi } from "@/features/auth/api/authApi";
import {
  ONBOARDING_PROCESSING_PHASES,
  PUBLIC_PAGES,
  SESSION_RESUMED_KEY,
} from "@/features/auth/constants";
import { useUserActions } from "@/features/auth/hooks/useUser";
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
  const { setUser, clearUser } = useUserActions();
  const searchParams = useSearchParams();
  const currentPath = usePathname();
  const hasIdentified = useRef(false);

  const { data, error } = useQuery({
    queryKey: ["current-user"],
    queryFn: () => authApi.fetchUserInfo(),
    staleTime: Infinity, // mutations update Zustand directly, so this only needs to fetch once per session
    retry: false, // auth failures shouldn't be retried
  });

  // Sync fetched data into Zustand store and run one-time side effects
  useEffect(() => {
    if (!data) return;

    setUser({
      userId: data.user_id,
      name: data.name,
      email: data.email,
      profilePicture: data.picture,
      timezone: data.timezone,
      onboarding: data.onboarding,
      selected_model: data.selected_model,
    });

    // Identify the persisted client session with the stable backend user ID.
    if (data.user_id && !hasIdentified.current) {
      identifyUser(data.user_id, {
        email: data.email,
        name: data.name,
        timezone: data.timezone,
        onboarding_completed: data.onboarding?.completed ?? false,
      });
      hasIdentified.current = true;
    }
  }, [data, setUser]);

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

  // OAuth redirect routing — isolated from store syncing so route changes
  // don't overwrite user state with stale query data. Resolved during render
  // (not in an effect) so the callback page never paints before redirecting;
  // `redirect` performs the same client-side navigation router.push did.
  const accessToken = searchParams.get("access_token");
  const refreshToken = searchParams.get("refresh_token");

  // Analytics for the OAuth login — fired pre-redirect (redirect() aborts the
  // render, so an effect here would never run). A module flag, not a ref:
  // refs must not be written during render. Exactly-once per page load.
  if (
    data &&
    accessToken &&
    refreshToken &&
    !readPendingCheckout() &&
    !hasTrackedOAuthLogin
  ) {
    hasTrackedOAuthLogin = true;
    trackEvent(ANALYTICS_EVENTS.USER_LOGGED_IN, {
      method: "workos_oauth",
    });

    // A pending checkout takes priority; useCheckoutResume redirects to Dodo.
    const needsOnboarding = !data.onboarding?.completed;
    const phase = data.onboarding?.phase;
    const isStillProcessing =
      !!phase && ONBOARDING_PROCESSING_PHASES.has(phase);

    if (needsOnboarding && currentPath !== "/onboarding") {
      redirect("/onboarding", RedirectType.push);
    }

    if (
      !needsOnboarding &&
      !isStillProcessing &&
      (currentPath === "/onboarding" || PUBLIC_PAGES.includes(currentPath))
    ) {
      redirect("/c", RedirectType.push);
    }
  }

  // Clear user state on auth failure
  useEffect(() => {
    if (!error) return;
    console.error("Error fetching user info:", error);
    clearUser();
    resetUser();
    hasIdentified.current = false;
  }, [error, clearUser]);
};

export default useFetchUser;
