/**
 * REST surface for the onboarding flow. Thin wrappers over `apiService` —
 * all auth, error toast, and analytics behaviour come from there. The WS
 * channel is owned separately by `useBackendSync`.
 */

import { authApi, type UserInfo } from "@/features/auth/api/authApi";
import { apiService } from "@/lib/api/service";

import type { PersonalizationData } from "../types/websocket";

export interface CompleteOnboardingArgs {
  name: string;
  profession: string;
  timezone: string;
  focus: string;
}

export interface CompleteOnboardingResponse {
  success: boolean;
  message: string;
  user?: UserInfo;
}

export interface PlatformConnectInfo {
  auth_url: string | null;
  auth_type: string;
  instructions: string | null;
  action_link: string | null;
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
 * GET /platform-links/{platform}/connect — returns either an OAuth URL to
 * pop open or an external action link (e.g. Telegram bot deep-link).
 */
export function getPlatformConnect(
  platform: string,
): Promise<PlatformConnectInfo> {
  return apiService.get<PlatformConnectInfo>(
    `/platform-links/${platform.toLowerCase()}/connect`,
    { silent: true },
  );
}
