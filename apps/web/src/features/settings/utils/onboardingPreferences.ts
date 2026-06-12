import type { OnboardingData } from "@/stores/userStore";

/**
 * Build the userStore update that mirrors a saved onboarding-preferences
 * payload. The backend replaces the whole preferences object on save, so the
 * store must mirror exactly what was sent for other settings sections to
 * build their next payload from fresh values.
 */
export const mergedOnboardingUpdate = (
  onboarding: OnboardingData | undefined,
  preferences: NonNullable<OnboardingData["preferences"]>,
): { onboarding: OnboardingData } => ({
  onboarding: {
    completed: onboarding?.completed ?? true,
    ...onboarding,
    preferences,
  },
});
