import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { ONBOARDING_PROCESSING_PHASES } from "@/features/auth/constants";
import { readPendingCheckout } from "@/features/pricing/lib/pendingCheckout";
import { useSetupStatus } from "@/features/setup-wizard/hooks/useSetupStatus";
import { usePathname } from "@/i18n/navigation";

import { useUser } from "./useUser";

export const useOnboardingGuard = () => {
  const user = useUser();
  const router = useRouter();
  const pathname = usePathname();
  // Only fetched when the guard is actually about to act — a self-host
  // instance replaces hosted onboarding with the /setup wizard.
  const potentiallyRedirecting =
    Boolean(user.email) &&
    user.onboarding !== undefined &&
    pathname !== "/onboarding";
  const { data: setupStatus } = useSetupStatus({
    enabled: potentiallyRedirecting,
  });

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
      } else if (pathname === "/setup" || setupStatus?.auth_mode === "local") {
        // Self-host replaces hosted onboarding with the /setup wizard — a
        // fresh local admin legitimately has no onboarding state, so never
        // push those users into the Gmail-scanning flow. Hosted behavior is
        // unchanged (setupStatus is undefined there and /setup isn't used).
      } else if (!isOnboardingCompleted) {
        // Not on onboarding page, onboarding not completed → redirect there
        router.push("/onboarding");
      }
    }
  }, [user.email, user.onboarding, router, pathname, setupStatus?.auth_mode]);
};
