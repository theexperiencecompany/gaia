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
  PlatformPreviewPlatform,
  PlatformScript,
  ProfessionArchetype,
  UserIdentity,
} from "./platformPreviewMessages.types";

export type {
  PlatformPreviewPlatform,
  PlatformScript,
  ProfessionArchetype,
  UserIdentity,
} from "./platformPreviewMessages.types";

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

function getArchetype(profession: string | undefined): ProfessionArchetype {
  if (!profession) return "default";
  return PROFESSION_TO_ARCHETYPE[profession.toLowerCase()] ?? "default";
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

const USER_PLACEHOLDER_NAME = "__user__";
const USER_PLACEHOLDER_AVATAR = "__user_avatar__";
const USER_COLOR = "#FFB37A";
const FALLBACK_USER_AVATAR = "/aryan-avatar.webp";

const BUILDER: ArchetypeScripts = {
  telegram: {
    title: "GAIA",
    subtitle: "bot",
    messages: [
      {
        from: "them",
        text: "morning! quick heads up, i pushed your 9am standup back to 10 so you've got a bit more breathing room.",
        time: "8:40",
      },
      {
        from: "them",
        text: "you have 2 code reviews waiting on you, and last night's deploy went through fine. nothing to worry about there.",
        time: "8:40",
      },
      {
        from: "me",
        text: "anything actually on fire i should know about?",
        time: "8:41",
        status: "read",
      },
      {
        from: "them",
        text: "nope, all quiet. go grab your coffee first.",
        time: "8:41",
      },
    ],
  },
  whatsapp: {
    title: "GAIA",
    messages: [
      {
        from: "them",
        text: "hey, your tech lead just replied on the migration thread and she wants to hop on a call today.",
        time: "11:02",
      },
      {
        from: "me",
        text: "ugh, can you draft a reply for me?",
        time: "11:02",
        status: "read",
      },
      {
        from: "them",
        text: "already done. i offered her 3pm or 4pm. want me to send it, or do you want to read it first?",
        time: "11:03",
      },
      { from: "me", text: "just send it", time: "11:03", status: "read" },
      {
        from: "them",
        text: "sent! she picked 3pm. i blocked it on your calendar and added a quick agenda.",
        time: "11:04",
      },
    ],
  },
  slack: {
    title: "eng",
    messages: [
      {
        author: "GAIA",
        authorColor: "#9CC3FF",
        text: "you've got 2 code reviews waiting today. one is a small fix, the other is a bigger change to how login works.",
        time: "9:12 AM",
      },
      {
        author: USER_PLACEHOLDER_NAME,
        avatar: USER_PLACEHOLDER_AVATAR,
        authorColor: USER_COLOR,
        text: "tell me about the bigger one",
        time: "9:13 AM",
      },
      {
        author: "GAIA",
        authorColor: "#9CC3FF",
        text: "it rewrites the login flow, so it really needs careful eyes before merging. want me to pull it up for you?",
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
        text: "this week's changelog is all written up. 14 updates, ready to publish whenever you are.",
        time: "Fri 5:30 PM",
      },
      {
        author: "GAIA",
        authorColor: "#9CC3FF",
        text: "want me to post it right now, or should i wait and auto publish it at 6?",
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
        text: "posted! also wanted to flag, one task has been stuck for over a week now. should i nudge the dev about it?",
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
      {
        from: "them",
        text: "morning! here's how your day is shaping up:",
        time: "8:30",
      },
      {
        from: "them",
        text: "you've got 3 internal meetings, the client presentation prep at 2pm, and a board update draft due by end of day.",
        time: "8:30",
      },
      {
        from: "me",
        text: "can you move the client prep earlier?",
        time: "8:31",
        status: "read",
      },
      {
        from: "them",
        text: "moved it to 11am and blocked off a full hour so you can actually focus.",
        time: "8:31",
      },
      {
        from: "me",
        text: "and start the board update for me",
        time: "8:32",
        status: "read",
      },
      {
        from: "them",
        text: "on it now. you'll have a first draft by noon.",
        time: "8:32",
      },
    ],
  },
  whatsapp: {
    title: "GAIA",
    messages: [
      {
        from: "them",
        text: "your client from yesterday's call followed up. they want pricing options by tomorrow.",
        time: "2:14 PM",
      },
      {
        from: "me",
        text: "draft 3 different options and show me first",
        time: "2:15 PM",
        status: "read",
      },
      {
        from: "them",
        text: "got it, working on it now. should be ready in about 10 minutes.",
        time: "2:15 PM",
      },
      {
        from: "them",
        text: "all done. 3 pricing tiers are sitting in your drafts. i also looped in your sales lead so they're in the loop.",
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
        text: "heads up, your client meeting is at 2pm today. i drafted talking points and saved them to your notes.",
        time: "1:05 PM",
      },
      {
        author: USER_PLACEHOLDER_NAME,
        avatar: USER_PLACEHOLDER_AVATAR,
        authorColor: USER_COLOR,
        text: "can you add last quarter's numbers too?",
        time: "1:06 PM",
      },
      {
        author: "GAIA",
        authorColor: "#9CC3FF",
        text: "added! revenue, retention, and customer satisfaction scores are all in the doc now.",
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
        text: "your monthly report is ready. growth was flat this month, but churn is down 1.2%.",
        time: "Mon 9:00 AM",
      },
      {
        author: "GAIA",
        authorColor: "#9CC3FF",
        text: "biggest win was enterprise sales, up 18% from last month.",
        time: "Mon 9:00 AM",
      },
      {
        author: USER_PLACEHOLDER_NAME,
        avatar: USER_PLACEHOLDER_AVATAR,
        authorColor: USER_COLOR,
        text: "post a quick summary in here too",
        time: "Mon 9:01 AM",
      },
      {
        author: "GAIA",
        authorColor: "#9CC3FF",
        text: "posted! i also flagged it so it'll come up in monday's standup.",
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
      {
        from: "them",
        text: "morning! here's the quick brief for today:",
        time: "7:45",
      },
      {
        from: "them",
        text: "investor follow up from maya, 2 new candidate intros to look at, and stripe just flagged a failed payment from a customer.",
        time: "7:45",
      },
      {
        from: "me",
        text: "fix the stripe thing first",
        time: "7:46",
        status: "read",
      },
      {
        from: "them",
        text: "already on it. i'm retrying the payment now. i'll update you in about 5 minutes.",
        time: "7:46",
      },
      {
        from: "them",
        text: "good news, the payment went through. customer's already been notified, all sorted.",
        time: "7:51",
      },
    ],
  },
  whatsapp: {
    title: "GAIA",
    messages: [
      {
        from: "them",
        text: "your lead from last week's demo just replied. she's interested and wants to set up a call.",
        time: "4:12 PM",
      },
      {
        from: "me",
        text: "book it. any time tomorrow works",
        time: "4:13 PM",
        status: "read",
      },
      {
        from: "them",
        text: "sent her 3 time slots and she picked 11am.",
        time: "4:14 PM",
      },
      {
        from: "them",
        text: "i also added a quick 5 minute prep summary to your calendar invite so you're not going in cold.",
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
        text: "your investor update goes out friday. the draft is ready in your notes whenever you want to take a look.",
        time: "10:14 AM",
      },
      {
        author: USER_PLACEHOLDER_NAME,
        avatar: USER_PLACEHOLDER_AVATAR,
        authorColor: USER_COLOR,
        text: "can you tighten up the numbers section?",
        time: "10:15 AM",
      },
      {
        author: "GAIA",
        authorColor: "#9CC3FF",
        text: "done! i trimmed it down to revenue, costs, and how long the cash will last. want me to send you a preview?",
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
        text: "12 personalized intros are queued up and ready to go out monday morning.",
        time: "Sun 8:00 PM",
      },
      {
        author: "GAIA",
        authorColor: "#9CC3FF",
        text: "fyi 3 of them are warm leads. they actually replied to your last message.",
        time: "Sun 8:00 PM",
      },
      {
        author: USER_PLACEHOLDER_NAME,
        avatar: USER_PLACEHOLDER_AVATAR,
        authorColor: USER_COLOR,
        text: "approve them all",
        time: "Sun 8:01 PM",
      },
      {
        author: "GAIA",
        authorColor: "#9CC3FF",
        text: "going out monday at 9am. i'll flag any replies as they come in.",
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
      {
        from: "them",
        text: "morning! two things on the agenda for you today:",
        time: "9:00",
      },
      {
        from: "them",
        text: "the reading list you started yesterday is still open, and friday's submission deadline is creeping up.",
        time: "9:00",
      },
      {
        from: "me",
        text: "pull the 3 most cited papers on the topic",
        time: "9:01",
        status: "read",
      },
      {
        from: "them",
        text: "on it. sending you the summaries shortly.",
        time: "9:01",
      },
      {
        from: "me",
        text: "and block 2 hours friday morning so i can actually write",
        time: "9:02",
        status: "read",
      },
      {
        from: "them",
        text: "blocked off. i'll also send you a soft reminder thursday so it doesn't sneak up on you.",
        time: "9:02",
      },
    ],
  },
  whatsapp: {
    title: "GAIA",
    messages: [
      {
        from: "them",
        text: "your supervisor just replied on the draft. she wants revisions to section 3.",
        time: "10:48",
      },
      {
        from: "me",
        text: "can you summarize what she's asking for?",
        time: "10:49",
        status: "read",
      },
      {
        from: "them",
        text: "three things basically: tighten up the methodology, add 2 more citations, and soften the conclusion a bit.",
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
        text: "5 candidates are queued up for you. pick whenever you're ready.",
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
        text: "your weekly reading digest is up. 6 new papers in your research area this week.",
        time: "Mon 8:30 AM",
      },
      {
        author: USER_PLACEHOLDER_NAME,
        avatar: USER_PLACEHOLDER_AVATAR,
        authorColor: USER_COLOR,
        text: "rank them for me by what's most important",
        time: "Mon 8:31 AM",
      },
      {
        author: "GAIA",
        authorColor: "#9CC3FF",
        text: "the top one is worth your monday. it actually cites a paper you bookmarked last month.",
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
        text: "this week's reading digest is up. 6 new papers in your area.",
        time: "Sun 7:00 PM",
      },
      {
        author: "GAIA",
        authorColor: "#9CC3FF",
        text: "one of them cites a paper you bookmarked last month. same author too.",
        time: "Sun 7:00 PM",
      },
      {
        author: USER_PLACEHOLDER_NAME,
        avatar: USER_PLACEHOLDER_AVATAR,
        authorColor: USER_COLOR,
        text: "summarize the top 3 for me",
        time: "Sun 7:01 PM",
      },
      {
        author: "GAIA",
        authorColor: "#9CC3FF",
        text: "summaries are in your notes, ranked by relevance to your current work.",
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
      {
        from: "them",
        text: "morning! looks like a pretty small day for you:",
        time: "8:30",
      },
      {
        from: "them",
        text: "one calendar event at 2pm, and a couple of emails worth a quick look.",
        time: "8:30",
      },
      {
        from: "me",
        text: "anything urgent?",
        time: "8:31",
        status: "read",
      },
      {
        from: "them",
        text: "nope, easy one. nothing time sensitive today.",
        time: "8:31",
      },
      {
        from: "me",
        text: "remind me to call mom at 7",
        time: "8:32",
        status: "read",
      },
      {
        from: "them",
        text: "set! i'll give you a nudge 5 minutes before so you're ready.",
        time: "8:32",
      },
    ],
  },
  whatsapp: {
    title: "GAIA",
    messages: [
      {
        from: "them",
        text: "sarah just got back to you. she's free for coffee on thursday.",
        time: "3:20 PM",
      },
      {
        from: "me",
        text: "book it for 4pm",
        time: "3:20 PM",
        status: "read",
      },
      {
        from: "them",
        text: "done, it's on your calendar.",
        time: "3:21 PM",
      },
      {
        from: "them",
        text: "want me to suggest a coffee spot somewhere between both of you?",
        time: "3:21 PM",
      },
      { from: "me", text: "yes please", time: "3:22 PM", status: "read" },
    ],
  },
  slack: {
    title: "general",
    messages: [
      {
        author: "GAIA",
        authorColor: "#9CC3FF",
        text: "your weekly digest is ready. nothing urgent this week, just the highlights.",
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
        text: "your annual review is due in 2 weeks. that's really the only firm deadline coming up.",
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
        text: "nothing urgent though, just the highlights this week.",
        time: "Sun 6:00 PM",
      },
      {
        author: USER_PLACEHOLDER_NAME,
        avatar: USER_PLACEHOLDER_AVATAR,
        authorColor: USER_COLOR,
        text: "anything with a deadline?",
        time: "Sun 6:01 PM",
      },
      {
        author: "GAIA",
        authorColor: "#9CC3FF",
        text: "yep, your annual review is due in 2 weeks.",
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
