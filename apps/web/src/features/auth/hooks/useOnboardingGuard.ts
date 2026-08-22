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
  const potentiallyRedirecting =
    Boolean(user.email) &&
    user.onboarding !== undefined &&
    pathname !== "/onboarding";
  const [isSelfHosted, setIsSelfHosted] = useState(false);

  useEffect(() => {
    if (!potentiallyRedirecting || isSelfHosted) return;
    let cancelled = false;
    providersApi
      .fetchSetupStatus()
      .then((s) => {
        if (!cancelled && s?.auth_mode === "local") setIsSelfHosted(true);
      })
      .catch(() => {
        // Unreachable / offline status must never break the guard — the
        // default (isSelfHosted=false) keeps hosted behavior intact.
      });
    return () => {
      cancelled = true;
    };
  }, [potentiallyRedirecting, isSelfHosted]);

  useEffect(() => {
    // A pending checkout must resume before onboarding routing kicks in.
    if (readPendingCheckout()) return;

    // Only proceed if user data is loaded with email and onboarding data is available
    if (user.email && user.onboarding !== undefined) {
      const isOnboardingCompleted = user.onboarding?.completed;
      const phase = user.onboarding?.phase;
      const isStillProcessing =
        !!phase && ONBOARDING_PROCESSING_PHASES.has(phase);

      if (pathname === "/onboarding") {
        // Don't redirect while the intelligence pipeline is still running.
        if (isOnboardingCompleted && !isStillProcessing) {
          router.push("/c");
        }
      } else if (isSelfHosted || pathname === "/setup") {
        // Self-host replaces hosted onboarding with the /setup wizard — a
        // fresh local admin legitimately has no onboarding state, so never
        // push those users into the Gmail-scanning flow. Hosted behavior is
        // unchanged (isSelfHosted stays false there and /setup isn't used).
      } else if (!isOnboardingCompleted) {
        // Not on onboarding page, onboarding not completed → redirect there
        router.push("/onboarding");
      }
    }
  }, [user.email, user.onboarding, router, pathname, isSelfHosted]);
};
