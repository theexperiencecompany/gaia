import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";

import { useUser } from "./useUser";

export const useOnboardingGuard = () => {
  const user = useUser();
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    // Only proceed if user data is loaded with email and onboarding data is available
    if (user.email && user.onboarding !== undefined) {
      const isOnboardingCompleted = user.onboarding?.completed;

      if (pathname === "/onboarding") {
        // If on onboarding page but already completed, redirect to main app
        if (isOnboardingCompleted) {
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
