import { apiBaseUrl } from "@/lib/api/client";

/**
 * A same-site path to land on after sign-in. Rejects `//evil.com` and
 * `/\evil.com`: browsers normalize `\` to `/`, making the latter protocol-relative.
 */
const SAFE_RETURN_PATH = /^\/[^/\\]/;

/** returnUrl when it is a safe same-site path to land on after sign-in, else undefined. */
export const safeReturnPath = (returnUrl?: string): string | undefined =>
  returnUrl && SAFE_RETURN_PATH.test(returnUrl) ? returnUrl : undefined;

/** The WorkOS sign-in URL; the API sends the user back to returnUrl when it is a safe path. */
export const oauthLoginUrl = (returnUrl?: string): string => {
  const safePath = safeReturnPath(returnUrl);
  return safePath
    ? `${apiBaseUrl}/oauth/login/workos?return_url=${encodeURIComponent(safePath)}`
    : `${apiBaseUrl}/oauth/login/workos`;
};

/** The instance's sign-in page, which picks local or WorkOS sign-in and returns to returnUrl. */
export const loginPagePath = (returnUrl: string): string =>
  `/login?return_url=${encodeURIComponent(returnUrl)}`;

export const handleAuthLogin = (returnUrl?: string) => {
  window.location.href = oauthLoginUrl(returnUrl);
};
