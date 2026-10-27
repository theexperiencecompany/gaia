/** Pages that render with no marketing navbar or footer. */
const BARE_ROUTES = new Set(["/desktop-login"]);

/** Auth pages a self-hosted instance serves as its own, not as GAIA's website. */
const SELFHOST_AUTH_ROUTES = new Set(["/login", "/signup"]);

/** Whether a landing-group page renders inside the hosted marketing navbar and footer. */
export function showsMarketingChrome(
  pathname: string,
  selfhost: boolean,
): boolean {
  if (BARE_ROUTES.has(pathname)) return false;
  return !(selfhost && SELFHOST_AUTH_ROUTES.has(pathname));
}
