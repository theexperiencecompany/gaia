import type { OnboardingData } from "@/stores/userStore";

type PreferencesPatch = Partial<NonNullable<OnboardingData["preferences"]>>;

/**
 * Build the userStore update that mirrors a saved onboarding-preferences patch.
 * The backend PATCHes only the fields each surface sends (field-level merge), so
 * the store must merge the patch into the existing preferences rather than
 * replace them — keeping fields owned by other settings surfaces intact.
 */
export const mergedOnboardingUpdate = (
  onboarding: OnboardingData | undefined,
  patch: PreferencesPatch,
): { onboarding: OnboardingData } => ({
  onboarding: {
    completed: onboarding?.completed ?? true,
    ...onboarding,
    preferences: { ...onboarding?.preferences, ...patch },
  },
});
