import type { BotPlatform } from "@/config/botPlatforms";

/** Where GAIA answers on each platform and what it accepts there (apps/bots/<platform>/src/adapter.ts). */
export const BOT_PLATFORM_REACH: Record<BotPlatform, string> = {
  discord:
    "DMs, plus @mentions and slash commands in servers. Voice notes, images and files.",
  telegram:
    "Private chats, plus @mentions in groups. Voice notes, photos and documents.",
  slack: "DMs, @mentions in channels and /gaia. Text only for now.",
  whatsapp: "One-on-one chats. Voice notes, images and documents.",
  imessage: "One-on-one chats. Voice notes, images and documents.",
};

/** The everyday subset of libs/shared/ts/src/bots/commands, grouped for the page. */
export const BOT_COMMAND_GROUPS = [
  { commands: ["/gaia"], description: "Ask GAIA anything as a slash command" },
  {
    commands: ["/todo", "/workflow"],
    description: "List, add and complete todos, and list and run workflows",
  },
  {
    commands: ["/new", "/stop"],
    description:
      "Start a fresh conversation, or stop the current reply and start fresh",
  },
  { commands: ["/status"], description: "Check whether this chat is linked" },
  { commands: ["/help"], description: "How to use GAIA, with every command" },
] as const;

export const BOTS_FAQS = [
  {
    question: "Does GAIA read every message in my group?",
    answer:
      "No. In Discord servers, Slack channels and Telegram groups it only responds to messages that @mention it or use a slash command. WhatsApp and iMessage chats with GAIA are one-on-one.",
  },
  {
    question: "Do people in one channel share a conversation?",
    answer:
      "No. GAIA keeps a separate conversation for each person in each channel or DM, so what someone else asked never becomes part of your context. Replies posted in a channel are still visible to everyone in it.",
  },
  {
    question: "Can I send voice notes and files?",
    answer:
      "On Discord, Telegram, WhatsApp and iMessage, yes. Voice notes up to 25 MB are transcribed and treated as your message, and images and documents up to 10 MB are attached to it. Videos and stickers are not supported yet. Slack is text only for now.",
  },
  {
    question: "Do I need a GAIA account?",
    answer:
      "Yes. Send /auth in a chat with GAIA to link it to your account; the link expires after 10 minutes. On GAIA Cloud, chatting through the bots needs GAIA Pro.",
  },
];
