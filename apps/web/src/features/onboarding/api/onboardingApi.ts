/**
 * REST surface for the onboarding flow. Thin wrappers over the typed `api` —
 * all auth, error toast, and analytics behaviour come from there.
 */

import type {
  MintPlatformLinkCodeResponse,
  OnboardingPreferences,
} from "@shared/api/generated";
import { api } from "@/lib/api/typed";

export type OnboardingPreferencesArgs = OnboardingPreferences;

/**
 * Writes Q1 + Q2 as soon as they are answered, well before the flow's final
 * `POST /onboarding`. Everything the server composes from the user's answers —
 * the platform-link opener above all — reads these fields, so they have to be
 * stored before anything that consumes them runs.
 *
 * Silent: the caller surfaces its own failure, because the answers not being
 * saved is not a generic request error to shrug at.
 */
export function saveOnboardingPreferences(args: OnboardingPreferencesArgs) {
  return api.patch("/api/v1/onboarding/preferences", {
    body: args,
    silent: true,
  });
}

export function resetOnboarding() {
  return api.post("/api/v1/onboarding/reset", { silent: true });
}

export type LinkCodeResponse = MintPlatformLinkCodeResponse;

/**
 * Mints the one-tap linking code for the platform-pick step.
 *
 * Silent: a failure here degrades to the plain bot links (the user types
 * `/auth`), and an error toast mid-onboarding would be worse than that.
 */
export function mintLinkCode() {
  return api.post("/api/v1/platform-links/code", { silent: true });
}
