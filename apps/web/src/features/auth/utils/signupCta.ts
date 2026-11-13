import { apiBaseUrl } from "@/lib/api/client";
import { isSelfhostWeb } from "@/lib/selfhost";

const SIGNUP_PAGE_PATH = "/signup";

/** WorkOS's hosted sign-up screen, reached straight from the API's login redirect. */
export const WORKOS_SIGNUP_URL = `${apiBaseUrl}/oauth/login/workos?screen_hint=sign-up`;

/**
 * Where a "Get started" CTA goes: WorkOS sign-up on hosted GAIA, the local
 * email/password page on a self-hosted build. The /signup page itself stays
 * for visitors who arrive from search.
 */
export function signupCtaHref(): string {
  return isSelfhostWeb() ? SIGNUP_PAGE_PATH : WORKOS_SIGNUP_URL;
}

/** The `navigation:cta_clicked` destination that matches `signupCtaHref`. */
export function signupCtaDestination(): "workos_oauth" | "/signup" {
  return isSelfhostWeb() ? SIGNUP_PAGE_PATH : "workos_oauth";
}
