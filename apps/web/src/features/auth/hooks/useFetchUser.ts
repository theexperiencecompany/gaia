"use client";

import { parseUserId } from "@gaia/shared/analytics/identity";
import { ApiError } from "@shared/api";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { RedirectType, redirect, useSearchParams } from "next/navigation";
import { useEffect, useRef } from "react";
import { PUBLIC_PAGES, SESSION_RESUMED_KEY } from "@/features/auth/constants";
import {
  clearCurrentUser,
  currentUserQueryOptions,
  useMayHaveSession,
} from "@/features/auth/hooks/useCurrentUser";
import { usePendingCheckout } from "@/features/pricing/hooks/usePendingCheckout";
import { usePathname } from "@/i18n/navigation";
import { identifyUser, resetUser, track } from "@/lib/analytics";
import { HTTP_UNAUTHORIZED } from "@/lib/api/outcome";

// Exactly-once guard for the OAuth login analytics event — module scope so it
// can be flipped during the render-phase redirect without writing a ref.
let hasTrackedOAuthLogin = false;

const isUnauthorized = (error: Error | null): boolean =>
  error instanceof ApiError && error.status === HTTP_UNAUTHORIZED;

/** Drive the current-user query; OAuth tokens in the URL always ask /me. */
const useFetchUser = () => {
  const queryClient = useQueryClient();
  const searchParams = useSearchParams();
  const currentPath = usePathname();
  const hasIdentified = useRef(false);
  const hasClearedOnUnauthorized = useRef(false);
  const pendingCheckout = usePendingCheckout();
  const accessToken = searchParams.get("access_token");
  const refreshToken = searchParams.get("refresh_token");
  const hasOAuthTokens = Boolean(accessToken && refreshToken);
  const mayHaveSession = useMayHaveSession();

  // The one driver of the current-user query: re-validates the persisted user on mount.
  // enabled reads the live query, so a user the persister restores after mount counts.
  const { data, error } = useQuery({
    ...currentUserQueryOptions,
    refetchOnMount: "always",
    enabled: (query) => hasOAuthTokens || mayHaveSession(query),
  });

  useEffect(() => {
    if (!data) return;
    // A user loaded means a live session again, so its later 401 must clear it too.
    hasClearedOnUnauthorized.current = false;

    // Identify the persisted client session with the stable backend user ID.
    if (data.user_id && !hasIdentified.current) {
      identifyUser(parseUserId(data.user_id), {
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
      track("user:session_resumed", {
        method: "wos_session_cookie",
        has_completed_onboarding: data.onboarding?.completed ?? false,
      });
      sessionStorage.setItem(SESSION_RESUMED_KEY, "true");
    }
  }, [data, currentPath]);

  // OAuth redirect resolved during render (not an effect) so the callback page
  // never paints before redirecting. Login analytics are server-side only
  // (track_login on the OAuth callback); emitting here would double-count.
  if (data && hasOAuthTokens && !pendingCheckout && !hasTrackedOAuthLogin) {
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

  // A transient /me failure keeps the cached user (and with it the marketing gate's
  // evidence of a session): only the API's 401 ends the session.
  useEffect(() => {
    if (error && !isUnauthorized(error)) {
      console.error("Error fetching user info:", error);
    }
  }, [error]);

  // A 401 drops the user from the persisted cache too. Guarded by a ref: removing the
  // query makes an app-page observer refetch and 401 again, in a loop.
  useEffect(() => {
    if (!isUnauthorized(error) || hasClearedOnUnauthorized.current) return;
    hasClearedOnUnauthorized.current = true;
    clearCurrentUser(queryClient);
    hasIdentified.current = false;
    // resetUser leaves an anonymous visitor's 401 alone.
    resetUser();
  }, [error, queryClient]);
};

export default useFetchUser;
