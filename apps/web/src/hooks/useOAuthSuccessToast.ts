"use client";

import { useQueryClient } from "@tanstack/react-query";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef } from "react";
import { toast } from "sonner";

/**
 * Global hook to handle OAuth success/error URL parameters and display toasts.
 * This should be used in the main layout to work across all pages.
 */
export function useOAuthSuccessToast() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const queryClient = useQueryClient();
  const processedRef = useRef<string | null>(null);

  useEffect(() => {
    const oauthSuccess = searchParams.get("oauth_success");
    const oauthError = searchParams.get("oauth_error");
    const integrationName = searchParams.get("integration");

    // Create a unique key for this set of params to prevent double-processing
    const paramsKey = `${oauthSuccess}-${oauthError}-${integrationName}`;

    // Skip if no OAuth params or already processed this exact set
    if ((!oauthSuccess && !oauthError) || processedRef.current === paramsKey) {
      return;
    }

    // Mark as processed
    processedRef.current = paramsKey;

    // Handle OAuth success
    if (oauthSuccess === "true") {
      const displayName = integrationName
        ? integrationName.charAt(0).toUpperCase() +
          integrationName.slice(1).replace(/_/g, " ")
        : "Integration";

      toast.success(`Connected to ${displayName}`);

      // Invalidate integration-related queries so they refresh
      queryClient.invalidateQueries({ queryKey: ["integrations"] });
      queryClient.invalidateQueries({ queryKey: ["tools", "available"] });
    }

    // Handle OAuth errors
    if (oauthError) {
      const errorMessages: Record<string, string> = {
        cancelled:
          "Authentication was cancelled. Please try again to connect your account.",
        access_denied:
          "Access was denied. Please grant the necessary permissions to continue.",
        no_code: "Authentication failed. No authorization code received.",
        invalid_state:
          "Authentication session expired or invalid. Please try again.",
        user_mismatch:
          "Authentication security error. Please log out and try again.",
        failed: "Authentication failed. Please try again.",
      };

      toast.error(
        errorMessages[oauthError] ||
          `Authentication failed: ${oauthError}. Please try again.`,
      );
    }

    // Clean up the URL by removing OAuth params
    const url = new URL(window.location.href);
    url.searchParams.delete("oauth_success");
    url.searchParams.delete("oauth_error");
    url.searchParams.delete("integration");

    // Replace URL without the OAuth params, keeping other params intact
    router.replace(url.pathname + url.search, { scroll: false });
  }, [searchParams, router, pathname, queryClient]);
}
