import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ONBOARDING_PROCESSING_PHASES } from "@/features/auth/constants";
import { readPendingCheckout } from "@/features/pricing/lib/pendingCheckout";
import { providersApi } from "@/features/settings/api/providersApi";
import { usePathname } from "@/i18n/navigation";

import { useUser } from "./useUser";

export const useOnboardingGuard = () => {
  const user = useUser();
  const router = useRouter();
  const pathname = usePathname();
  // Only fetched when the guard is actually about to act — a self-host
  // instance replaces hosted onboarding with the /setup wizard. Plain state,
  // not react-query: this hook mounts ABOVE the app's QueryClientProvider.
  // ``null`` means unknown: never redirect on an unknown instance type, or a
  // self-host admin gets flashed into the hosted flow before status arrives.
  const potentiallyRedirecting =
    Boolean(user.email) &&
    user.onboarding !== undefined &&
    pathname !== "/onboarding" &&
    pathname !== "/setup";
  const [authMode, setAuthMode] = useState<"workos" | "local" | null>(null);

  useEffect(() => {
    if (!potentiallyRedirecting || authMode !== null) return;
    let cancelled = false;
    providersApi
      .fetchSetupStatus()
      .then((s) => {
        if (!cancelled)
          setAuthMode(s?.auth_mode === "local" ? "local" : "workos");
      })
      .catch(() => {
        // Status unreachable → assume hosted so existing behavior holds; the
        // request is retried by the re-render loop only if deps change.
        if (!cancelled) setAuthMode("workos");
      });
    return () => {
      cancelled = true;
    };
  }, [potentiallyRedirecting, authMode]);

  useEffect(() => {
    // A pending checkout must resume before onboarding routing kicks in.
    if (readPendingCheckout()) return;

    // Only proceed if user data is loaded with email and onboarding data is
    // available, and we KNOW which kind of instance this is.
    if (user.email && user.onboarding !== undefined && authMode !== null) {
      const isOnboardingCompleted = user.onboarding?.completed;
      const phase = user.onboarding?.phase;
      const isStillProcessing =
        !!phase && ONBOARDING_PROCESSING_PHASES.has(phase);

      if (pathname === "/onboarding") {
        // Don't redirect while the intelligence pipeline is still running.
        if (isOnboardingCompleted && !isStillProcessing) {
          router.push("/c");
        }
      } else if (pathname === "/setup") {
        // The self-host wizard replaces hosted onboarding entirely.
      } else if (authMode === "local") {
        // Local instances have no hosted onboarding pipeline: a fresh local
        // admin legitimately has no onboarding state and must land straight
        // in chat instead of the Gmail-scanning flow.
      } else if (!isOnboardingCompleted) {
        // Hosted instance, onboarding not completed → redirect there.
        router.push("/onboarding");
      }
    }
  }, [user.email, user.onboarding, router, pathname, authMode]);
};
