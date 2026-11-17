/** The WorkOS session cookie the API sets on sign-in. */
export const WOS_SESSION_COOKIE = "wos_session";

/** The local (self-host) session cookie; LOCAL_SESSION_COOKIE in apps/api/app/utils/local_auth_utils.py. */
export const LOCAL_SESSION_COOKIE = "gaia_session";

/**
 * The non-secret cookie the API writes beside every session cookie (readable by the
 * web, on the site web and API share); SESSION_HINT_COOKIE in apps/api/app/constants/auth.py.
 */
export const SESSION_HINT_COOKIE = "gaia_signed_in";
