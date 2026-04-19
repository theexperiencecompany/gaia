"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef } from "react";
import { authApi } from "@/features/auth/api/authApi";
import { PUBLIC_PAGES, SESSION_RESUMED_KEY } from "@/features/auth/constants";
import { useUserActions } from "@/features/auth/hooks/useUser";
import { usePathname } from "@/i18n/navigation";
import {
  ANALYTICS_EVENTS,
  identifyUser,
  resetUser,
  trackEvent,
} from "@/lib/analytics";

const useFetchUser = () => {
  const { setUser, clearUser } = useUserActions();
  const router = useRouter();
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

    // Identify user in PostHog for analytics (only once per session)
    if (data.email && !hasIdentified.current) {
      identifyUser(data.email, {
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
  // don't overwrite user state with stale query data.
  useEffect(() => {
    if (!data) return;

    const accessToken = searchParams.get("access_token");
    const refreshToken = searchParams.get("refresh_token");
    if (!accessToken || !refreshToken) return;

    const needsOnboarding = !data.onboarding?.completed;
    if (needsOnboarding && currentPath !== "/onboarding") {
      router.push("/onboarding");
      return;
    }

    if (
      !needsOnboarding &&
      (currentPath === "/onboarding" || PUBLIC_PAGES.includes(currentPath))
    ) {
      router.push("/c");
    }
  }, [data, searchParams, router, currentPath]);

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
