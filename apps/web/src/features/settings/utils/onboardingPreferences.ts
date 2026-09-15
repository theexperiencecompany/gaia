import type { OnboardingData } from "@/features/auth/api/authApi";

type PreferencesPatch = Partial<NonNullable<OnboardingData["preferences"]>>;

/**
 * Build the current-user patch that mirrors a saved onboarding-preferences
 * update. The backend PATCHes only the fields each surface sends (field-level
 * merge), so the cached user must merge the patch into the existing
 * preferences rather than replace them — keeping fields owned by other settings surfaces intact.
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
