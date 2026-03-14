"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";
import Spinner from "@/components/ui/spinner";
import { toast } from "@/lib/toast";

export default function RedirectPage() {
  const router = useRouter();

  useEffect(() => {
    const handleRedirect = () => {
      const params = new URLSearchParams(window.location.search);
      // Check for OAuth errors
      const oauthError = params.get("oauth_error");
      const oauthSuccess = params.get("oauth_success");

      if (oauthSuccess === "true") {
        // Show success toast for successful OAuth connection
        toast.success("Integration connected successfully!");
        // Stay on current page or redirect to integrations page
        // The frontend will automatically refresh integration status
        return;
      }

      if (oauthError) {
        // Handle OAuth errors with appropriate toasts
        switch (oauthError) {
          case "cancelled":
            toast.error(
              "Authentication was cancelled. Please try again to connect your account.",
            );
            break;
          case "access_denied":
            toast.error(
              "Access was denied. Please grant the necessary permissions to continue.",
            );
            break;
          case "no_code":
            toast.error(
              "Authentication failed. No authorization code received.",
            );
            break;
          case "invalid_state":
            toast.error(
              "Authentication session expired or invalid. Please try again.",
            );
            break;
          case "user_mismatch":
            toast.error(
              "Authentication security error. Please log out and try again.",
            );
            break;
          case "failed":
            toast.error("Authentication failed. Please try again.");
            break;
          default:
            toast.error(
              `Authentication failed: ${oauthError}. Please try again.`,
            );
        }

        // Redirect to login page on error
        router.replace("/login");
        return;
      }

      // Default redirect to main app if no specific parameters
      router.replace("/c");
    };

    // Add a small delay to ensure the page has rendered before showing toast
    const timer = setTimeout(handleRedirect, 100);

    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Show a simple loading message while redirecting
  return (
    <div className="flex min-h-screen items-center justify-center">
      <Spinner />
    </div>
  );
}
