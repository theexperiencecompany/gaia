/**
 * REST surface for the onboarding flow. Thin wrappers over the typed `api` —
 * all auth, error toast, and analytics behaviour come from there.
 */

import type {
  MintPlatformLinkCodeResponse,
  OnboardingAnswers,
  OnboardingPhaseUpdateRequest,
} from "@shared/api/generated";
import { api } from "@/lib/api/typed";

/**
 * Writes Q1 + Q2 as soon as they are answered, well before the flow's final
 * `POST /onboarding`. Everything the server composes from the user's answers —
 * the platform-link opener above all — reads these fields, so they have to be
 * stored before anything that consumes them runs.
 *
 * Silent: the caller surfaces its own failure, because the answers not being
 * saved is not a generic request error to shrug at.
 */
export function saveOnboardingAnswers(answers: OnboardingAnswers) {
  return api.put("/api/v1/onboarding/answers", {
    body: answers,
    silent: true,
  });
}

/**
 * Tells the server the wizard reached a step only the browser sees. The
 * server stamps it once per onboarding run and emits its analytics event, so
 * a reload re-reporting the same step is harmless.
 */
export function reportOnboardingStep(
  phase: OnboardingPhaseUpdateRequest["phase"],
) {
  return api.post("/api/v1/onboarding/phase", {
    body: { phase },
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

/** The accounts linked to this user, polled while the wizard waits on a link. */
export function fetchPlatformLinks() {
  return api.get("/api/v1/platform-links", { silent: true });
}
