// ── Stage copy ────────────────────────────────────────────────────────────────

export const NEEDS_HINT = "You can always add more later.";

export const PAYMENT_INTRO_LINES = [
  "GAIA is one plan with everything in it.",
  "Pick monthly or yearly and we can get going.",
];

export const PAID_REVEAL_LINES = [
  "You're in. Everything is unlocked.",
  "Here's your receipt.",
];

export const PLATFORM_INTRO_LINES = [
  "I work best where you already text.",
  "Pick one and I'll reach you there when something needs you: the morning brief, an email that can't wait, a meeting about to start.",
];

export const FINISHING_MESSAGE = "Getting your chat ready…";

/** Static greeting — no LLM call anywhere in onboarding. */
export function greetingLines(firstName: string | undefined): string[] {
  const salutation = firstName ? `Hey ${firstName}, you're in.` : "You're in.";
  return [
    salutation,
    "From here on I keep your inbox, calendar, reminders and follow-ups moving. One last thing to set up.",
  ];
}
