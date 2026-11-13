import { RedirectType, redirect } from "next/navigation";
import { useEntitlement } from "@/features/pricing/hooks/useEntitlement";
import { usePendingCheckout } from "@/features/pricing/hooks/usePendingCheckout";
import { usePathname } from "@/i18n/navigation";

import { useCurrentUser } from "./useCurrentUser";

export const useOnboardingGuard = () => {
  const user = useCurrentUser();
  const pathname = usePathname();
  const entitlement = useEntitlement();
  const pendingCheckout = usePendingCheckout();

  // A pending checkout must resume before onboarding routing kicks in.
  if (pendingCheckout) return;

  // Only proceed if user data is loaded with email and onboarding data is available
  if (!user.email || user.onboarding === undefined) return;

  // Resolved during render, not an effect, so a guarded page never paints
  // before redirecting. Replaces (not pushes), like every guard — a pushed
  // redirect leaves Back bouncing right back out.

  // A never-paid account finishes on the wizard's paywall step; a lapsed one
  // stays in the app, where the UpgradeModal stands.
  const needsOnboarding =
    !user.onboarding.completed || entitlement === "never_subscribed";

  if (pathname === "/onboarding") {
    // Submitting the answers IS completion now — nothing is generated
    // afterwards, so there is no processing phase to hold the user here.
    if (!needsOnboarding && entitlement !== "unknown") {
      // Completion seeds GAIA's "Getting started" conversation, so land the
      // user inside it rather than on an empty composer. A seed that failed is
      // never a reason to strand them — fall back to the chat home.
      const seededConversationId =
        user.onboarding.getting_started_conversation_id;
      redirect(
        seededConversationId ? `/c/${seededConversationId}` : "/c",
        RedirectType.replace,
      );
    }
  } else if (pathname === "/setup") {
    // The self-host wizard REPLACES hosted onboarding: a local instance has no
    // onboarding pipeline (the API reports completed=True for it), so the branch
    // below would fire here and bounce the admin off their own setup wizard.
  } else if (needsOnboarding) {
    redirect("/onboarding", RedirectType.replace);
  }
};
