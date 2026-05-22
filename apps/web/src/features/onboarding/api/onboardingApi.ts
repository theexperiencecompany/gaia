/**
 * REST surface for the onboarding flow. Thin wrappers over `apiService` —
 * all auth, error toast, and analytics behaviour come from there. The WS
 * channel is owned separately by `useBackendSync`.
 */

import { authApi, type UserInfo } from "@/features/auth/api/authApi";
import { apiService } from "@/lib/api/service";

import type { ClarifyQuestion } from "../types";
import type { PersonalizationData } from "../types/websocket";

export interface CompleteOnboardingClarifyAnswer {
  id: string;
  kind: string;
  question: string;
  value: string | null;
}

export interface CompleteOnboardingArgs {
  name: string;
  profession: string;
  timezone: string;
  focus: string;
  clarify_answers?: CompleteOnboardingClarifyAnswer[];
}

export interface ClarifyQuestionsResponse {
  questions: ClarifyQuestion[];
}

export interface CompleteOnboardingResponse {
  success: boolean;
  message: string;
  user?: UserInfo;
}

// A 409 means a prior submission was already accepted — callers treat it as success.
export function completeOnboarding(
  args: CompleteOnboardingArgs,
): Promise<CompleteOnboardingResponse> {
  return authApi.completeOnboarding(args);
}

export function getPersonalization(): Promise<PersonalizationData> {
  return apiService.get<PersonalizationData>("/onboarding/personalization", {
    silent: true,
  });
}

export function postPhase(phase: string): Promise<unknown> {
  return apiService.post("/onboarding/phase", { phase });
}

export function resetOnboarding(): Promise<unknown> {
  return apiService.post("/onboarding/reset", {}, { silent: true });
}

export function getClarifyQuestions(args: {
  name: string;
  profession: string;
  focus: string;
}): Promise<ClarifyQuestionsResponse> {
  return apiService.post<ClarifyQuestionsResponse>(
    "/onboarding/clarify-questions",
    args,
    { silent: true },
  );
}
