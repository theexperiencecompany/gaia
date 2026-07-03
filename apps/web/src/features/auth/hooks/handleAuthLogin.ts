import { apiauth } from "@/lib/api/client";

/**
 * Kick off the WorkOS sign-in flow. When `returnUrl` is a safe in-app path, the
 * OAuth callback sends the user back there after login (the API validates it
 * via `is_safe_redirect_path`); otherwise the flow lands on the default
 * post-login route.
 */
export const handleAuthLogin = (returnUrl?: string) => {
  const base = `${apiauth.getUri()}oauth/login/workos`;
  window.location.href = returnUrl
    ? `${base}?return_url=${encodeURIComponent(returnUrl)}`
    : base;
};
