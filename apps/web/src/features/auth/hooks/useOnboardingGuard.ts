import { RedirectType, redirect } from "next/navigation";
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

  if (pathname === "/onboarding") {
    // Submitting the answers IS completion now — nothing is generated
    // afterwards, so there is no processing phase to hold the user here.
    if (isOnboardingCompleted) {
      // Completion seeds GAIA's "Getting started" conversation, so land the
      // user inside it rather than on an empty composer. A seed that failed is
      // never a reason to strand them — fall back to the chat home.
      const seededConversationId =
        user.onboarding?.first_message_conversation_id;
      redirect(
        seededConversationId ? `/c/${seededConversationId}` : "/c",
        RedirectType.push,
      );
    }
  } else if (!isOnboardingCompleted) {
    // If not on onboarding page but onboarding is not completed, redirect to onboarding
    redirect("/onboarding", RedirectType.push);
  }
};
