/** Public Turnstile site key for the /contact form; inlined at build time. */
export const TURNSTILE_SITE_KEY = process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY;

export const CONTACT_FORM_MESSAGES = {
  INVALID_EMAIL: "Enter a valid email address so we can reply",
  VERIFICATION_FAILED:
    "We could not verify that you are human. Reload the page and try again.",
  NOT_CONFIGURED:
    "The contact form is unavailable right now. Use one of the email addresses on this page instead.",
} as const;
