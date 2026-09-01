/**
 * REST surface for the onboarding flow. Thin wrappers over `apiService` —
 * all auth, error toast, and analytics behaviour come from there.
 */

import { authApi, type UserInfo } from "@/features/auth/api/authApi";
import { apiService } from "@/lib/api/service";

export interface CompleteOnboardingArgs {
  profession: string;
  /** Must be `OnboardingNeed` values; the API rejects anything else. */
  needs: string[];
  timezone: string;
}

export interface CompleteOnboardingResponse {
  success: boolean;
  message: string;
  user?: UserInfo;
}

// A replayed submission is accepted server-side (the atomic gate returns the
// existing document), so callers can retry without special-casing.
export function completeOnboarding(
  args: CompleteOnboardingArgs,
): Promise<CompleteOnboardingResponse> {
  return authApi.completeOnboarding(args);
}

export function resetOnboarding(): Promise<unknown> {
  return apiService.post("/onboarding/reset", {}, { silent: true });
}
