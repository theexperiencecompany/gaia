"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useEffect } from "react";
import { toast } from "sonner";

import Spinner from "@/components/ui/spinner";

export default function RedirectPage() {
  const router = useRouter();
  const searchParams = useSearchParams();

  useEffect(() => {
    const handleRedirect = () => {
      // Check for OAuth errors
      const oauthError = searchParams.get("oauth_error");

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
  }, [router, searchParams]);

  // Show a simple loading message while redirecting
  return (
    <div className="flex min-h-screen items-center justify-center">
      <Spinner />
    </div>
  );
}
