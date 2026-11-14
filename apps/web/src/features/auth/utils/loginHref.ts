/** The sign-in page, returning to returnUrl (a path on this site) once signed in. */
export function loginHref(returnUrl: string): string {
  return `/login?return_url=${encodeURIComponent(returnUrl)}`;
}
