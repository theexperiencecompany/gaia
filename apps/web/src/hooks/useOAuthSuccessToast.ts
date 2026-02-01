"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef } from "react";
import { toast } from "sonner";

import { useSendMessage } from "@/hooks/useSendMessage";

// Module-level Set to track which OAuth callbacks we've already processed
// This persists across React Strict Mode double-mounts
const processedOAuthCallbacks = new Set<string>();

/**
 * Global hook to handle OAuth success/error URL parameters and display toasts.
 * This should be used in the main layout to work across all pages.
 */
export function useOAuthSuccessToast() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const queryClient = useQueryClient();
  const sendMessage = useSendMessage();
  // Use ref to hold stable reference to sendMessage
  const sendMessageRef = useRef(sendMessage);
  sendMessageRef.current = sendMessage;

  useEffect(() => {
    const oauthSuccess = searchParams.get("oauth_success");
    const oauthError = searchParams.get("oauth_error");
    const integrationName = searchParams.get("integration");

    // Skip if no OAuth params
    if (!oauthSuccess && !oauthError) return;

    // For success, use a simpler key without timestamp to dedupe properly
    const dedupeKey = `${oauthSuccess}-${integrationName}`;

    // Skip if we've already processed this exact OAuth callback
    if (processedOAuthCallbacks.has(dedupeKey)) {
      return;
    }

    // Mark as processed
    processedOAuthCallbacks.add(dedupeKey);

    // Clean up after a delay to allow for future OAuth flows
    setTimeout(() => {
      processedOAuthCallbacks.delete(dedupeKey);
    }, 5000);

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

      // Automatically send a message to continue the chat
      sendMessageRef.current(`Hey I just connected ${displayName}`);
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
  }, [searchParams, router, queryClient]);
}
