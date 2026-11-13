import type { BotPlatform } from "@/config/botPlatforms";

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

export const ANSWERS_SAVE_FAILED_MESSAGE =
  "Hmm, I couldn't save your answers. Check your connection and try again.";
export const ANSWERS_SAVING_LABEL = "Saving your answers";

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

/** What to do in the app the deep link opened, so the link lands. */
export const AWAITING_LINK_LINES: Record<BotPlatform, string> = {
  telegram: "Tap Start in Telegram and I'll pick it up here.",
  whatsapp:
    "Send the message that just opened in WhatsApp and I'll pick it up here.",
  imessage: "Send that text from your iPhone and I'll pick it up here.",
  slack: "Finish connecting in Slack and I'll pick it up here.",
  discord: "Finish connecting in Discord and I'll pick it up here.",
};
export const AWAITING_LINK_SKIP_LABEL = "Skip for now";
export const AWAITING_LINK_OTHER_APP_LABEL = "Use another app";
