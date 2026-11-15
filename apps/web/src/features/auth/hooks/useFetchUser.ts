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

/**
 * Drive the current-user query. knownSessionOnly (marketing pages) asks /me only
 * when this browser holds a signed-in user or carries OAuth tokens: the session
 * cookie is the API's own, so the web cannot see it and a stranger would get a 401.
 */
const useFetchUser = ({
  knownSessionOnly = false,
}: {
  knownSessionOnly?: boolean;
} = {}) => {
  const queryClient = useQueryClient();
  const searchParams = useSearchParams();
  const currentPath = usePathname();
  const hasIdentified = useRef(false);
  const hasClearedOnError = useRef(false);
  const hasResetOnUnauthorized = useRef(false);
  const pendingCheckout = usePendingCheckout();
  const accessToken = searchParams.get("access_token");
  const refreshToken = searchParams.get("refresh_token");
  const hasOAuthTokens = Boolean(accessToken && refreshToken);

  // The one driver of the current-user query: re-validates the persisted user on mount.
  // enabled reads the live query, so a user the persister restores after mount counts.
  const { data, error } = useQuery({
    ...currentUserQueryOptions,
    refetchOnMount: "always",
    enabled: (query) =>
      !knownSessionOnly || hasOAuthTokens || query.state.data !== undefined,
  });

  useEffect(() => {
    if (!data) return;

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

  // Clear user state on a failed /me, dropping it from the persisted cache too.
  // Guarded by a ref: removing the query makes this observer refetch, so an
  // unguarded effect would remove it again on the next failure, in a loop.
  useEffect(() => {
    if (!error || hasClearedOnError.current) return;
    hasClearedOnError.current = true;
    // A 401 is the API's answer for a signed-out browser, not a failure.
    if (!isUnauthorized(error)) {
      console.error("Error fetching user info:", error);
    }
    clearCurrentUser(queryClient);
    hasIdentified.current = false;
  }, [error, queryClient]);

  // Only a 401 ends the identified session, so it is guarded on its own: a 5xx
  // that cleared the cache first must not swallow the 401 a refetch then returns.
  useEffect(() => {
    if (hasResetOnUnauthorized.current) return;
    if (!isUnauthorized(error)) return;
    hasResetOnUnauthorized.current = true;
    // resetUser leaves an anonymous visitor's 401 alone.
    resetUser();
  }, [error]);
};

export default useFetchUser;
