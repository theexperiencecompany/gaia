// ── Stage copy ────────────────────────────────────────────────────────────────

export const PAYMENT_INTRO_LINES = [
  "It's one plan, everything included.",
  "Cancel whenever. Monthly or yearly?",
];

export const PAID_REVEAL_LINES = ["You're in.", "Here's your receipt."];

export const PLATFORM_INTRO_LINES = [
  "Last thing: where do you want me to text you?",
  "You'll get a brief every morning, a heads-up when an email actually needs you, and a nudge before meetings.",
  "Pick one.",
];

export const FINISHING_MESSAGE = "Getting your chat ready…";

/** Static greeting — no LLM call anywhere in onboarding. */
export function greetingLines(firstName: string | undefined): string[] {
  const salutation = firstName ? `Hey ${firstName}.` : "Hey.";
  return [salutation, "You're all set. One last thing before we start."];
}
