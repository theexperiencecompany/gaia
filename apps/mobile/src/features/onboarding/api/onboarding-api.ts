import type {
  OnboardingPhaseUpdateRequest,
  OnboardingPhaseUpdateResponse,
  OnboardingStatusResponse,
} from "@gaia/shared/api/generated";
import { apiService } from "@/lib/api";

export const getOnboardingStatus = () =>
  apiService.get<OnboardingStatusResponse>("/onboarding/status");

/** Reports a wizard step the app reached; the server stamps and counts it once per onboarding run. */
export const reportOnboardingStep = (
  phase: OnboardingPhaseUpdateRequest["phase"],
) =>
  apiService.post<OnboardingPhaseUpdateResponse>("/onboarding/phase", {
    phase,
  });
