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

export interface OnboardingPreferencesArgs {
  profession: string;
  /** Must be `OnboardingNeed` values; the API rejects anything else. */
  needs: string[];
}

/**
 * Writes Q1 + Q2 as soon as they are answered, well before the flow's final
 * `POST /onboarding`. Everything the server composes from the user's answers —
 * the platform-link opener above all — reads these fields, so they have to be
 * stored before anything that consumes them runs.
 *
 * Silent: the caller surfaces its own failure, because the answers not being
 * saved is not a generic request error to shrug at.
 */
export function saveOnboardingPreferences(
  args: OnboardingPreferencesArgs,
): Promise<unknown> {
  return apiService.patch("/onboarding/preferences", args, { silent: true });
}

export function resetOnboarding(): Promise<unknown> {
  return apiService.post("/onboarding/reset", {}, { silent: true });
}

export interface LinkCodeResponse {
  /** Single-use code the bot redeems on the user's first message. */
  code: string;
  /** The opening message, composed server-side from Q1 + Q2. */
  first_message: string;
  /** `first_message` plus ` #<code>` — what a WhatsApp/iMessage user sends. */
  handoff_text: string;
  /**
   * Deep link per platform, already carrying the code. iMessage is absent by
   * construction: its number is assigned per user by the connect call, so that
   * link is built client-side from `handoff_text`.
   */
  links: Partial<Record<string, string>>;
}

/**
 * Mints the one-tap linking code for the platform-pick step.
 *
 * Silent: a failure here degrades to the plain bot links (the user types
 * `/auth`), and an error toast mid-onboarding would be worse than that.
 */
export function mintLinkCode(): Promise<LinkCodeResponse> {
  return apiService.post<LinkCodeResponse>(
    "/platform-links/code",
    {},
    { silent: true },
  );
}
