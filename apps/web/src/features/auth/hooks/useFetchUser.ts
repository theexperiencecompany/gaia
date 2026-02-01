"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useRef } from "react";

import { authApi } from "@/features/auth/api/authApi";
import { useUserActions } from "@/features/auth/hooks/useUser";
import { identifyUser, resetUser, trackEvent, ANALYTICS_EVENTS } from "@/lib/analytics";

export const authPages = ["/login", "/signup"];
export const publicPages = [...authPages, "/terms", "/privacy", "/contact"];

const useFetchUser = () => {
  const { setUser, clearUser } = useUserActions();
  const searchParams = useSearchParams();
  const router = useRouter();
  const currentPath = usePathname();
  const hasIdentified = useRef(false);

  const fetchUserInfo = useCallback(async () => {
    try {
      const accessToken = searchParams.get("access_token");
      const refreshToken = searchParams.get("refresh_token");

      const data = await authApi.fetchUserInfo();

      setUser({
        userId: data?.user_id,
        name: data?.name,
        email: data?.email,
        profilePicture: data?.picture,
        timezone: data?.timezone,
        onboarding: data?.onboarding,
        selected_model: data?.selected_model,
      });

      // Identify user in PostHog for analytics (only once per session)
      if (data?.email && !hasIdentified.current) {
        identifyUser(data.email, {
          email: data.email,
          name: data.name,
          timezone: data.timezone,
          onboarding_completed: data.onboarding?.completed ?? false,
        });
        hasIdentified.current = true;

        // Track login event if coming from OAuth redirect
        if (accessToken || refreshToken) {
          trackEvent(ANALYTICS_EVENTS.USER_LOGGED_IN, {
            method: "workos",
            has_completed_onboarding: data.onboarding?.completed ?? false,
          });
        }
      }

      // Check if onboarding is needed and prevent navigation loops
      if (accessToken && refreshToken) {
        const needsOnboarding = !data?.onboarding?.completed;

        if (needsOnboarding && currentPath !== "/onboarding") {
          router.push("/onboarding");
        } else if (!needsOnboarding && (currentPath === "/onboarding" || publicPages.includes(currentPath))) {
          router.push("/c");
        }
      }
    } catch (e: unknown) {
      console.error("Error fetching user info:", e);
      clearUser();
      resetUser();
      hasIdentified.current = false;
    }
  }, [searchParams, setUser, clearUser, router, currentPath]);

  useEffect(() => {
    fetchUserInfo();
  }, [fetchUserInfo]);

  return { fetchUserInfo };
};

export default useFetchUser;
