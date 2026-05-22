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

/**
 * POST /onboarding — kicks off the personalization pipeline server-side.
 * Returns the updated user on success. A 409 means the server already
 * accepted a prior submission and is treated as success by callers.
 */
export function completeOnboarding(
  args: CompleteOnboardingArgs,
): Promise<CompleteOnboardingResponse> {
  return authApi.completeOnboarding(args);
}

/** GET /onboarding/personalization — full snapshot. Silent (no toast). */
export function getPersonalization(): Promise<PersonalizationData> {
  return apiService.get<PersonalizationData>("/onboarding/personalization", {
    silent: true,
  });
}

/** POST /onboarding/phase — bookkeeping; failures are non-fatal. */
export function postPhase(phase: string): Promise<unknown> {
  return apiService.post("/onboarding/phase", { phase });
}

/** POST /onboarding/reset — wipes server-side onboarding artifacts. Silent. */
export function resetOnboarding(): Promise<unknown> {
  return apiService.post("/onboarding/reset", {}, { silent: true });
}

/**
 * POST /onboarding/clarify-questions — LLM-generated 3-question follow-up
 * for the no-Gmail path. Silent (failures fall back to a hardcoded set on
 * the server so the user always gets something to answer).
 */
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
