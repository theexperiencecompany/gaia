"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef } from "react";
import { authApi } from "@/features/auth/api/authApi";
import { useUserActions } from "@/features/auth/hooks/useUser";
import { usePathname } from "@/i18n/navigation";
import {
  ANALYTICS_EVENTS,
  identifyUser,
  resetUser,
  trackEvent,
} from "@/lib/analytics";

export const authPages = ["/login", "/signup"];
export const publicPages = [...authPages, "/terms", "/privacy", "/contact"];

const useFetchUser = () => {
  const { setUser, clearUser } = useUserActions();
  const searchParams = useSearchParams();
  const router = useRouter();
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

      const accessToken = searchParams.get("access_token");
      const refreshToken = searchParams.get("refresh_token");
      if (accessToken || refreshToken) {
        trackEvent(ANALYTICS_EVENTS.USER_LOGGED_IN, {
          method: "workos",
          has_completed_onboarding: data.onboarding?.completed ?? false,
        });
      }
    }

    // OAuth redirect routing — only runs when tokens are present in URL
    const accessToken = searchParams.get("access_token");
    const refreshToken = searchParams.get("refresh_token");
    if (accessToken && refreshToken) {
      const needsOnboarding = !data.onboarding?.completed;
      if (needsOnboarding && currentPath !== "/onboarding") {
        router.push("/onboarding");
      } else if (
        !needsOnboarding &&
        (currentPath === "/onboarding" || publicPages.includes(currentPath))
      ) {
        router.push("/c");
      }
    }
  }, [data, setUser, searchParams, router, currentPath]);

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
