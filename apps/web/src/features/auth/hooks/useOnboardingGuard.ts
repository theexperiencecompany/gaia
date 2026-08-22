import { RedirectType, redirect } from "next/navigation";
import { ONBOARDING_PROCESSING_PHASES } from "@/features/auth/constants";
import { readPendingCheckout } from "@/features/pricing/lib/pendingCheckout";
import { usePathname } from "@/i18n/navigation";

import { useUser } from "./useUser";

export const useOnboardingGuard = () => {
  const user = useUser();
  const pathname = usePathname();

  // A pending checkout must resume before onboarding routing kicks in.
  if (readPendingCheckout()) return;

  // Only proceed if user data is loaded with email and onboarding data is available
  if (!user.email || user.onboarding === undefined) return;

  // Resolved during render (not in an effect) so a guarded page never paints
  // before redirecting; `redirect` performs the same client-side navigation
  // router.push did.
  const isOnboardingCompleted = user.onboarding?.completed;
  const phase = user.onboarding?.phase;
  const isStillProcessing = !!phase && ONBOARDING_PROCESSING_PHASES.has(phase);

  if (pathname === "/onboarding") {
    // Don't redirect while the intelligence pipeline is still running.
    if (isOnboardingCompleted && !isStillProcessing) {
      redirect("/c", RedirectType.push);
    }
  } else if (!isOnboardingCompleted) {
    // If not on onboarding page but onboarding is not completed, redirect to onboarding
    redirect("/onboarding", RedirectType.push);
  }
};
