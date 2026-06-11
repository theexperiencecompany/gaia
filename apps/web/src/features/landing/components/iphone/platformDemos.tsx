import type { ReactNode } from "react";

import type { ChatMessageItem, ChatPlatform } from "./ChatDemo";

export interface ActionLink {
  label: string;
  href: string;
  external?: boolean;
}

export interface PhoneConfig {
  screenBackground?: string;
  statusBarTone?: "auto" | "light" | "dark";
}

export interface DemoConfig {
  title?: string;
  subtitle?: string;
  messages: ChatMessageItem[];
}

export interface Platform {
  id: ChatPlatform;
  name: string;
  icon: string | ReactNode;
  comingSoon?: boolean;
  primaryAction: ActionLink;
  phone: PhoneConfig;
  demo: DemoConfig;
}

const AVATAR_ARYAN = "/aryan-avatar.webp";

export function IMessageChipIcon({ size = 20 }: { size?: number }) {
  return (
    // biome-ignore lint/a11y/noSvgWithoutTitle: decorative brand icon, hidden from a11y tree
    <svg width={size} height={size} viewBox="0 0 20 20" aria-hidden>
      <rect width="20" height="20" rx="4.5" fill="#25D057" />
      <path
        d="M10 3.8C6.63 3.8 3.9 6.22 3.9 9.2c0 1.67.84 3.16 2.16 4.16-.04.58-.29 1.54-1.21 2.24 0 0 1.78.06 3.2-1.05.59.15 1.2.25 1.87.25 3.37 0 6.1-2.42 6.1-5.4S13.37 3.8 10 3.8z"
        fill="white"
      />
    </svg>
  );
}

export const PLATFORMS: Platform[] = [
  {
    id: "whatsapp",
    name: "WhatsApp",
    icon: "/images/icons/macos/whatsapp.webp",
    primaryAction: {
      label: "Message on WhatsApp",
      href: "https://wa.me/12762088737",
      external: true,
    },
    phone: { screenBackground: "#F6F6F6" },
    demo: {
      title: "GAIA",
      messages: [
        {
          from: "me",
          text: "what's on my plate today?",
          time: "9:14",
          status: "read",
        },
        {
          from: "them",
          text: "4 meetings back to back from 9.30, plus that investor draft you flagged yesterday",
          time: "9:14",
        },
        {
          from: "them",
          text: "want me to push standup to 11 so you have a coffee window?",
          time: "9:14",
        },
        {
          from: "me",
          text: "yes pls. also remind me to call mom at 8 🙏",
          time: "9:15",
          status: "read",
        },
        {
          from: "them",
          text: "done & done 🫡",
          time: "9:15",
        },
      ],
    },
  },
  {
    id: "telegram",
    name: "Telegram",
    icon: "/images/icons/macos/telegram.webp",
    primaryAction: {
      label: "Message on Telegram",
      href: "https://t.me/heygaia_bot",
      external: true,
    },
    phone: { screenBackground: "#F6F6F6" },
    demo: {
      title: "GAIA",
      subtitle: "bot",
      messages: [
        {
          from: "me",
          text: "summarise my inbox",
          time: "14:02",
          status: "read",
        },
        {
          from: "them",
          text: "you've got 12 unread. 3 actually need you, the rest is noise",
          time: "14:03",
        },
        {
          from: "them",
          text: "drafting replies to the linear founder + the recruiter rn",
          time: "14:03",
        },
        {
          from: "me",
          text: "also book me to NYC next thursday",
          time: "14:04",
          status: "read",
        },
        {
          from: "them",
          text: "looking… delta has $189 out at 8am, lands 11ish. lock it in?",
          time: "14:04",
        },
      ],
    },
  },
  {
    id: "slack",
    name: "Slack",
    icon: "/images/icons/macos/slack.webp",
    primaryAction: {
      label: "Install in Slack",
      href: "/slack-bot",
    },
    phone: {},
    demo: {
      title: "design",
      subtitle: "42 members",
      messages: [
        {
          author: "Aryan",
          avatar: AVATAR_ARYAN,
          text: "@GAIA standup post for design? pull from yesterday's threads",
          time: "10:24 AM",
        },
        {
          author: "GAIA",
          text: "pulled this from 4 open PRs and 6 figma comments since yesterday 🧵",
          time: "10:24 AM",
          reactions: [
            { emoji: "🎉", count: 4 },
            { emoji: "🔥", count: 2 },
          ],
        },
        {
          author: "Aryan",
          avatar: AVATAR_ARYAN,
          text: "send it. also draft a reply to the PM thread in #product",
          time: "10:25 AM",
        },
        {
          author: "GAIA",
          text: "on it. DMing you the draft in 30s",
          time: "10:26 AM",
        },
      ],
    },
  },
  {
    id: "discord",
    name: "Discord",
    icon: "/images/icons/macos/discord.webp",
    primaryAction: {
      label: "Add to Your Server",
      href: "https://heygaia.io/discord-bot",
      external: true,
    },
    phone: { screenBackground: "#1E1F22", statusBarTone: "light" },
    demo: {
      title: "general",
      messages: [
        {
          author: "Aryan",
          avatar: AVATAR_ARYAN,
          authorColor: "#F47FFF",
          text: "@GAIA ship digest for the week?",
          time: "9:14 PM",
          reactions: [{ emoji: "👍", count: 3 }],
        },
        {
          author: "GAIA",
          authorColor: "#9CC3FF",
          text: "12 PRs merged, 4 features shipped, 2 incidents resolved 🚀",
          time: "9:14 PM",
        },
        {
          author: "Aryan",
          avatar: AVATAR_ARYAN,
          authorColor: "#F47FFF",
          text: "post it in #releases",
          time: "9:15 PM",
        },
        {
          author: "GAIA",
          authorColor: "#9CC3FF",
          text: "posted, ping me if anyone has follow-ups",
          time: "9:15 PM",
        },
      ],
    },
  },
  {
    id: "imessage",
    name: "iMessage",
    icon: <IMessageChipIcon />,
    comingSoon: true,
    primaryAction: { label: "Coming Soon", href: "" },
    phone: { screenBackground: "#FFFFFF" },
    demo: {
      title: "GAIA",
      messages: [
        {
          from: "me",
          text: "reschedule my 3pm to tomorrow same time",
          time: "2:58 PM",
          status: "read",
        },
        {
          from: "them",
          text: "done. rescheduled and invite updated",
        },
        {
          from: "me",
          text: "also add a note to call sarah before it",
          time: "3:04 PM",
          status: "read",
        },
        {
          from: "them",
          text: "added. anything else?",
        },
      ],
    },
  },
];
