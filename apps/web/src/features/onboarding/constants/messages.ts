// ── Stage copy ────────────────────────────────────────────────────────────────

export function paymentIntroLines(firstName: string | undefined): string[] {
  return [
    firstName
      ? `So ${firstName}, quick thing before we go on. I'm not an app you're buying, I'm someone you're hiring.`
      : "Quick thing before we go on. I'm not an app you're buying, I'm someone you're hiring.",
    "A person doing all this costs a salary. I cost about a dollar a day.",
    "So, monthly or yearly?",
  ];
}

export const FINISHING_MESSAGE = "One sec, starting our first chat…";
export const FINISH_FAILED_MESSAGE =
  "Hmm, I couldn't finish setting up our chat. Mind trying again?";
export const FINISH_CTA_LABEL = "Start chatting";
export const FINISH_RETRY_LABEL = "Try again";

/** The first words after the receipt. Static: no LLM call anywhere in onboarding. */
export const PLATFORM_INTRO_LINES = [
  "Last thing! Which app do you basically live in?",
  "That's where I'll be. Send me anything from anywhere, one text and it's handled. And if something needs you, I'll text you first.",
];
