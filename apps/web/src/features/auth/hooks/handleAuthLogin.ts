import { apiBaseUrl } from "@/lib/api/client";

/**
 * A same-site path to land on after sign-in. Rejects `//evil.com` and
 * `/\evil.com`: browsers normalize `\` to `/`, making the latter protocol-relative.
 */
const SAFE_RETURN_PATH = /^\/[^/\\]/;

/** The WorkOS sign-in URL; the API sends the user back to returnUrl when it is a safe path. */
export const oauthLoginUrl = (returnUrl?: string): string =>
  returnUrl && SAFE_RETURN_PATH.test(returnUrl)
    ? `${apiBaseUrl}/oauth/login/workos?return_url=${encodeURIComponent(returnUrl)}`
    : `${apiBaseUrl}/oauth/login/workos`;

export const handleAuthLogin = (returnUrl?: string) => {
  window.location.href = oauthLoginUrl(returnUrl);
};
