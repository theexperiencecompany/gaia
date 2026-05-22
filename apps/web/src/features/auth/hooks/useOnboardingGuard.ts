import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { ONBOARDING_PROCESSING_PHASES } from "@/features/auth/constants";
import { usePathname } from "@/i18n/navigation";

import { useUser } from "./useUser";

export const useOnboardingGuard = () => {
  const user = useUser();
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
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
      } else {
        // If not on onboarding page but onboarding is not completed, redirect to onboarding
        if (!isOnboardingCompleted) {
          router.push("/onboarding");
        }
      }
    }
  }, [user.email, user.onboarding, router, pathname]);
};
