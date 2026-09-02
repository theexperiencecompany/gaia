// ── Stage copy ────────────────────────────────────────────────────────────────

export const NEEDS_HINT = "You can always add more later.";

export const PAYMENT_INTRO = "One thing before we start:";

export const PAID_REVEAL_TITLE = "Welcome to GAIA Pro!";

export const PAID_REVEAL_BODY = "You're on Pro. Everything is unlocked.";

export const PLATFORM_INTRO =
  "Tell me where you already text and I'll reach you there when something needs you: the morning brief, an email that can't wait, a meeting about to start.";

export const FINISHING_MESSAGE = "Getting your chat ready…";

/** Static greeting — no LLM call anywhere in onboarding. */
export function greetingMessage(firstName: string | undefined): string {
  const salutation = firstName ? `Hey ${firstName}.` : "Hey.";
  return `${salutation} I'm GAIA. Inbox, calendar, reminders, follow-ups: I keep them moving. One last thing to set up.`;
}
