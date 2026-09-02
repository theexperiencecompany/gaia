// ── Stage copy ────────────────────────────────────────────────────────────────

export const NEEDS_HINT = "You can always add more later.";

export const PAYMENT_INTRO = "One thing before we start:";

export const PAID_REVEAL_TITLE = "Welcome to GAIA Pro!";

export const PAID_REVEAL_BODY =
  "You're all set. Every Pro feature is unlocked. Let's get to work.";

export const PLATFORM_INTRO =
  "Tell me where you already hang out and I'll text you when it matters, morning briefings, urgent emails, calendar nudges, deadline reminders, anything that can't wait.";

export const FINISHING_MESSAGE = "Getting your chat ready…";

/** Static greeting — no LLM call anywhere in onboarding. */
export function greetingMessage(firstName: string | undefined): string {
  const salutation = firstName ? `Hey ${firstName} — ` : "Hey — ";
  return `${salutation}I'm GAIA. I handle the busywork: inbox, reminders, follow-ups, the stuff that eats your day. Let's set you up.`;
}
