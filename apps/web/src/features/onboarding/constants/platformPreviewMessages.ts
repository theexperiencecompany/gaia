/**
 * Profession-keyed message scripts for the platform preview shown in the
 * `platforms` onboarding stage. The 20 profession enum values are grouped
 * into 5 archetypes; each archetype owns three scripts (one per platform)
 * that demonstrate the three things the copy promises: morning briefings,
 * urgent email flags, and workflow-finished pings.
 *
 * Rebucket professions or rewrite scripts here, the preview component is
 * data-driven and has no other coupling to profession.
 */

import type {
  ChatMessageItem,
  ChatPlatform,
} from "@/features/landing/components/iphone/ChatDemo";

export type PlatformPreviewPlatform = Extract<
  ChatPlatform,
  "telegram" | "whatsapp" | "slack" | "discord"
>;

export type ProfessionArchetype =
  | "builder"
  | "operator"
  | "founder"
  | "scholar"
  | "default";

const PROFESSION_TO_ARCHETYPE: Record<string, ProfessionArchetype> = {
  engineer: "builder",
  developer: "builder",
  designer: "builder",

  manager: "operator",
  consultant: "operator",
  analyst: "operator",
  accountant: "operator",
  sales: "operator",
  marketing: "operator",

  entrepreneur: "founder",
  freelancer: "founder",

  student: "scholar",
  teacher: "scholar",
  researcher: "scholar",
  doctor: "scholar",
  lawyer: "scholar",
  writer: "scholar",

  artist: "default",
  retired: "default",
  other: "default",
};

export function getArchetype(
  profession: string | undefined,
): ProfessionArchetype {
  if (!profession) return "default";
  return PROFESSION_TO_ARCHETYPE[profession.toLowerCase()] ?? "default";
}

export interface PlatformScript {
  title: string;
  subtitle?: string;
  messages: ChatMessageItem[];
}

type ArchetypeScripts = Record<PlatformPreviewPlatform, PlatformScript>;

export const PLATFORM_PREVIEW_ORDER: PlatformPreviewPlatform[] = [
  "telegram",
  "whatsapp",
  "slack",
  "discord",
];

export const PLATFORM_LABELS: Record<PlatformPreviewPlatform, string> = {
  telegram: "Telegram",
  whatsapp: "WhatsApp",
  slack: "Slack",
  discord: "Discord",
};

export const PLATFORM_ICONS: Record<PlatformPreviewPlatform, string> = {
  telegram: "/images/icons/macos/telegram.webp",
  whatsapp: "/images/icons/macos/whatsapp.webp",
  slack: "/images/icons/macos/slack.webp",
  discord: "/images/icons/macos/discord.webp",
};

/**
 * Sentinel values for user-attributed messages in Slack/Discord scripts.
 * `hydrateScript()` swaps these for the live user's name + avatar at render.
 */
const USER_PLACEHOLDER_NAME = "__user__";
const USER_PLACEHOLDER_AVATAR = "__user_avatar__";
const USER_COLOR = "#FFB37A";
const FALLBACK_USER_AVATAR = "/aryan-avatar.webp";

// ── Scripts ──────────────────────────────────────────────────────────────────
// Each archetype has three scripts, one per platform. Keep them short
// (2–4 messages), the preview only has ~220px of vertical room.

const BUILDER: ArchetypeScripts = {
  telegram: {
    title: "GAIA",
    subtitle: "bot",
    messages: [
      { from: "them", text: "morning. standup in 20.", time: "8:40" },
      {
        from: "them",
        text: "2 PRs waiting on your review, and the staging deploy from last night went green.",
        time: "8:40",
      },
      {
        from: "me",
        text: "anything actually on fire?",
        time: "8:41",
        status: "read",
      },
      { from: "them", text: "nope. coffee first.", time: "8:41" },
      { from: "me", text: "push standup to 10", time: "8:42", status: "read" },
      { from: "them", text: "done. notified the team.", time: "8:42" },
    ],
  },
  whatsapp: {
    title: "GAIA",
    messages: [
      {
        from: "them",
        text: "your tech lead just replied on the migration thread, wants a call today.",
        time: "11:02",
      },
      {
        from: "me",
        text: "ugh. draft me a reply?",
        time: "11:02",
        status: "read",
      },
      {
        from: "them",
        text: "done. offered 3 and 4pm. want me to send or you wanna read it first?",
        time: "11:03",
      },
      { from: "me", text: "send it", time: "11:03", status: "read" },
      { from: "them", text: "sent. she picked 3.", time: "11:04" },
    ],
  },
  slack: {
    title: "eng",
    messages: [
      {
        author: "GAIA",
        authorColor: "#9CC3FF",
        text: "PR review queue: 2 waiting on you, 1 ready to merge once you ack.",
        time: "9:12 AM",
      },
      {
        author: USER_PLACEHOLDER_NAME,
        avatar: USER_PLACEHOLDER_AVATAR,
        authorColor: USER_COLOR,
        text: "summarise the two i need to review",
        time: "9:13 AM",
      },
      {
        author: "GAIA",
        authorColor: "#9CC3FF",
        text: "first is a small refactor in auth, second adds the new rate limiter, riskier.",
        time: "9:13 AM",
      },
    ],
  },
  discord: {
    title: "releases",
    messages: [
      {
        author: "GAIA",
        authorColor: "#9CC3FF",
        text: "weekly changelog is drafted, 14 PRs, 3 dependency bumps.",
        time: "Fri 5:30 PM",
      },
      {
        author: "GAIA",
        authorColor: "#9CC3FF",
        text: "ping me to post it, or i'll auto-publish at 6.",
        time: "Fri 5:30 PM",
      },
      {
        author: USER_PLACEHOLDER_NAME,
        avatar: USER_PLACEHOLDER_AVATAR,
        authorColor: USER_COLOR,
        text: "post it now",
        time: "Fri 5:31 PM",
      },
      {
        author: "GAIA",
        authorColor: "#9CC3FF",
        text: "posted. also flagged 1 PR that's been stale a week, nudge the author?",
        time: "Fri 5:31 PM",
      },
    ],
  },
};

const OPERATOR: ArchetypeScripts = {
  telegram: {
    title: "GAIA",
    subtitle: "bot",
    messages: [
      { from: "them", text: "good morning. here's the day:", time: "8:30" },
      {
        from: "them",
        text: "3 internal syncs, the QBR prep at 2, and a board update draft due EOD.",
        time: "8:30",
      },
      {
        from: "me",
        text: "move QBR prep earlier?",
        time: "8:31",
        status: "read",
      },
      {
        from: "them",
        text: "shifted to 11. blocked an hour for it.",
        time: "8:31",
      },
      {
        from: "me",
        text: "also draft a board update outline",
        time: "8:32",
        status: "read",
      },
      {
        from: "them",
        text: "drafting now. you'll have it by noon.",
        time: "8:32",
      },
    ],
  },
  whatsapp: {
    title: "GAIA",
    messages: [
      {
        from: "them",
        text: "client from yesterday's call followed up, they want pricing options by tomorrow.",
        time: "2:14 PM",
      },
      {
        from: "me",
        text: "draft 3 tiers and send to me first",
        time: "2:15 PM",
        status: "read",
      },
      { from: "them", text: "on it. you'll have it in 10.", time: "2:15 PM" },
      {
        from: "them",
        text: "ready in your drafts. cc'd the AE.",
        time: "2:24 PM",
      },
    ],
  },
  slack: {
    title: "leadership",
    messages: [
      {
        author: "GAIA",
        authorColor: "#9CC3FF",
        text: "QBR prep is at 2pm. drafted talking points in your notes.",
        time: "1:05 PM",
      },
      {
        author: USER_PLACEHOLDER_NAME,
        avatar: USER_PLACEHOLDER_AVATAR,
        authorColor: USER_COLOR,
        text: "pull last quarter's numbers too",
        time: "1:06 PM",
      },
      {
        author: "GAIA",
        authorColor: "#9CC3FF",
        text: "added. revenue, retention, NPS, all in the doc.",
        time: "1:06 PM",
      },
    ],
  },
  discord: {
    title: "leadership",
    messages: [
      {
        author: "GAIA",
        authorColor: "#9CC3FF",
        text: "monthly metrics rollup is ready. growth flat, churn down 1.2%.",
        time: "Mon 9:00 AM",
      },
      {
        author: "GAIA",
        authorColor: "#9CC3FF",
        text: "biggest mover: enterprise pipeline +18%.",
        time: "Mon 9:00 AM",
      },
      {
        author: USER_PLACEHOLDER_NAME,
        avatar: USER_PLACEHOLDER_AVATAR,
        authorColor: USER_COLOR,
        text: "post a tl;dr here too",
        time: "Mon 9:01 AM",
      },
      {
        author: "GAIA",
        authorColor: "#9CC3FF",
        text: "posted. flagged for monday's standup.",
        time: "Mon 9:01 AM",
      },
    ],
  },
};

const FOUNDER: ArchetypeScripts = {
  telegram: {
    title: "GAIA",
    subtitle: "bot",
    messages: [
      { from: "them", text: "morning. quick read:", time: "7:45" },
      {
        from: "them",
        text: "investor follow-up from Maya, 2 candidate intros, and stripe flagged a failed payment.",
        time: "7:45",
      },
      {
        from: "me",
        text: "deal with stripe first",
        time: "7:46",
        status: "read",
      },
      {
        from: "them",
        text: "already retrying. i'll update you in 5.",
        time: "7:46",
      },
      {
        from: "them",
        text: "stripe went through. customer notified. all clean.",
        time: "7:51",
      },
    ],
  },
  whatsapp: {
    title: "GAIA",
    messages: [
      {
        from: "them",
        text: "your lead from the demo last week just replied, interested, wants a call.",
        time: "4:12 PM",
      },
      {
        from: "me",
        text: "book it. anytime tomorrow",
        time: "4:13 PM",
        status: "read",
      },
      { from: "them", text: "sent 3 slots. she picked 11.", time: "4:14 PM" },
      {
        from: "them",
        text: "added a 5-min prep brief to your calendar invite.",
        time: "4:14 PM",
      },
    ],
  },
  slack: {
    title: "founders",
    messages: [
      {
        author: "GAIA",
        authorColor: "#9CC3FF",
        text: "investor update goes out friday. draft ready in your notes.",
        time: "10:14 AM",
      },
      {
        author: USER_PLACEHOLDER_NAME,
        avatar: USER_PLACEHOLDER_AVATAR,
        authorColor: USER_COLOR,
        text: "tighten the metrics section",
        time: "10:15 AM",
      },
      {
        author: "GAIA",
        authorColor: "#9CC3FF",
        text: "done. cut the fluff, kept ARR + burn + runway. want a preview?",
        time: "10:15 AM",
      },
    ],
  },
  discord: {
    title: "sales",
    messages: [
      {
        author: "GAIA",
        authorColor: "#9CC3FF",
        text: "weekly outreach is queued, 12 personalized intros ready.",
        time: "Sun 8:00 PM",
      },
      {
        author: "GAIA",
        authorColor: "#9CC3FF",
        text: "fyi 3 are warm, replied to your last touch.",
        time: "Sun 8:00 PM",
      },
      {
        author: USER_PLACEHOLDER_NAME,
        avatar: USER_PLACEHOLDER_AVATAR,
        authorColor: USER_COLOR,
        text: "approve them",
        time: "Sun 8:01 PM",
      },
      {
        author: "GAIA",
        authorColor: "#9CC3FF",
        text: "going out monday 9am. i'll flag any replies.",
        time: "Sun 8:01 PM",
      },
    ],
  },
};

const SCHOLAR: ArchetypeScripts = {
  telegram: {
    title: "GAIA",
    subtitle: "bot",
    messages: [
      { from: "them", text: "morning. two things on today:", time: "9:00" },
      {
        from: "them",
        text: "the lit review you flagged yesterday and a deadline reminder, submission closes friday.",
        time: "9:00",
      },
      {
        from: "me",
        text: "pull the 3 most cited papers on the topic",
        time: "9:01",
        status: "read",
      },
      { from: "them", text: "sending you the summaries now.", time: "9:01" },
      {
        from: "me",
        text: "also block 2 hours friday morning to write",
        time: "9:02",
        status: "read",
      },
      {
        from: "them",
        text: "blocked. and set a soft reminder thursday.",
        time: "9:02",
      },
    ],
  },
  whatsapp: {
    title: "GAIA",
    messages: [
      {
        from: "them",
        text: "your supervisor replied on the draft, wants revisions to section 3.",
        time: "10:48",
      },
      {
        from: "me",
        text: "summarise their notes for me",
        time: "10:49",
        status: "read",
      },
      {
        from: "them",
        text: "3 asks: tighten methodology, add 2 citations, soften the conclusion.",
        time: "10:49",
      },
      {
        from: "me",
        text: "find me citation options for the first two",
        time: "10:50",
        status: "read",
      },
      {
        from: "them",
        text: "5 candidates queued. pick when you're ready.",
        time: "10:51",
      },
    ],
  },
  slack: {
    title: "lab",
    messages: [
      {
        author: "GAIA",
        authorColor: "#9CC3FF",
        text: "your weekly reading digest is up, 6 new papers in your area.",
        time: "Mon 8:30 AM",
      },
      {
        author: USER_PLACEHOLDER_NAME,
        avatar: USER_PLACEHOLDER_AVATAR,
        authorColor: USER_COLOR,
        text: "rank them for me",
        time: "Mon 8:31 AM",
      },
      {
        author: "GAIA",
        authorColor: "#9CC3FF",
        text: "top one is worth your monday. one cites a paper you bookmarked last month.",
        time: "Mon 8:31 AM",
      },
    ],
  },
  discord: {
    title: "research",
    messages: [
      {
        author: "GAIA",
        authorColor: "#9CC3FF",
        text: "weekly reading digest is up, 6 new papers in your area.",
        time: "Sun 7:00 PM",
      },
      {
        author: "GAIA",
        authorColor: "#9CC3FF",
        text: "one cites a paper you bookmarked last month, same author.",
        time: "Sun 7:00 PM",
      },
      {
        author: USER_PLACEHOLDER_NAME,
        avatar: USER_PLACEHOLDER_AVATAR,
        authorColor: USER_COLOR,
        text: "summarise the top 3",
        time: "Sun 7:01 PM",
      },
      {
        author: "GAIA",
        authorColor: "#9CC3FF",
        text: "summaries are in your notes. ranked by relevance.",
        time: "Sun 7:01 PM",
      },
    ],
  },
};

const DEFAULT_SCRIPTS: ArchetypeScripts = {
  telegram: {
    title: "GAIA",
    subtitle: "bot",
    messages: [
      { from: "them", text: "morning. small day today:", time: "8:30" },
      {
        from: "them",
        text: "one calendar event at 2, and a couple of emails worth a look.",
        time: "8:30",
      },
      { from: "me", text: "anything urgent?", time: "8:31", status: "read" },
      { from: "them", text: "nope. easy one.", time: "8:31" },
      {
        from: "me",
        text: "remind me to call mom at 7",
        time: "8:32",
        status: "read",
      },
      {
        from: "them",
        text: "set. i'll nudge you 5 minutes before.",
        time: "8:32",
      },
    ],
  },
  whatsapp: {
    title: "GAIA",
    messages: [
      {
        from: "them",
        text: "got a reply from sarah, she's free for coffee thursday.",
        time: "3:20 PM",
      },
      { from: "me", text: "book it for 4", time: "3:20 PM", status: "read" },
      { from: "them", text: "done. added to your calendar.", time: "3:21 PM" },
      {
        from: "them",
        text: "want me to suggest a spot near both of you?",
        time: "3:21 PM",
      },
      { from: "me", text: "yes pls", time: "3:22 PM", status: "read" },
    ],
  },
  slack: {
    title: "general",
    messages: [
      {
        author: "GAIA",
        authorColor: "#9CC3FF",
        text: "your weekly digest is ready. nothing urgent, just the highlights.",
        time: "Sun 6:00 PM",
      },
      {
        author: USER_PLACEHOLDER_NAME,
        avatar: USER_PLACEHOLDER_AVATAR,
        authorColor: USER_COLOR,
        text: "anything i should look at first?",
        time: "Sun 6:01 PM",
      },
      {
        author: "GAIA",
        authorColor: "#9CC3FF",
        text: "your annual review is due in 2 weeks, that's the only date-locked thing.",
        time: "Sun 6:01 PM",
      },
    ],
  },
  discord: {
    title: "personal",
    messages: [
      {
        author: "GAIA",
        authorColor: "#9CC3FF",
        text: "your weekly digest is ready. a few things worth a glance.",
        time: "Sun 6:00 PM",
      },
      {
        author: "GAIA",
        authorColor: "#9CC3FF",
        text: "nothing urgent, just the highlights.",
        time: "Sun 6:00 PM",
      },
      {
        author: USER_PLACEHOLDER_NAME,
        avatar: USER_PLACEHOLDER_AVATAR,
        authorColor: USER_COLOR,
        text: "anything date-locked?",
        time: "Sun 6:01 PM",
      },
      {
        author: "GAIA",
        authorColor: "#9CC3FF",
        text: "yep, annual review's due in 2 weeks.",
        time: "Sun 6:01 PM",
      },
    ],
  },
};

const ARCHETYPE_SCRIPTS: Record<ProfessionArchetype, ArchetypeScripts> = {
  builder: BUILDER,
  operator: OPERATOR,
  founder: FOUNDER,
  scholar: SCHOLAR,
  default: DEFAULT_SCRIPTS,
};

export interface UserIdentity {
  name: string | undefined;
  avatar: string | undefined;
}

export function getPlatformScript(
  profession: string | undefined,
  platform: PlatformPreviewPlatform,
  user: UserIdentity = { name: undefined, avatar: undefined },
): PlatformScript {
  const archetype = getArchetype(profession);
  const raw = ARCHETYPE_SCRIPTS[archetype][platform];
  const liveName = user.name?.trim() || "you";
  const liveAvatar = user.avatar?.trim() || FALLBACK_USER_AVATAR;
  return {
    ...raw,
    messages: raw.messages.map((m) => ({
      ...m,
      author: m.author === USER_PLACEHOLDER_NAME ? liveName : m.author,
      avatar: m.avatar === USER_PLACEHOLDER_AVATAR ? liveAvatar : m.avatar,
    })),
  };
}
