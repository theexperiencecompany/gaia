// ── Stage copy ────────────────────────────────────────────────────────────────

export const NEEDS_HINT = "You can always add more later.";

export const PAYMENT_INTRO_LINES = [
  "One plan with everything in it: your inbox, calendar and todos handled every day, on every app GAIA is on.",
  "Cancel any time. Pick monthly or yearly to start.",
];

export const PAID_REVEAL_LINES = [
  "You're in. Everything is unlocked.",
  "Here's your receipt.",
];

export const PLATFORM_INTRO_LINES = [
  "I work best where you already text.",
  "A brief every morning before your first meeting.",
  "A heads-up when an email actually needs you, and a nudge before a meeting starts.",
  "Pick one and I'll reach you there.",
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
