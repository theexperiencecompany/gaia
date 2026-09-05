/**
 * Profession-keyed message scripts for the platform preview shown in the
 * `platformPick` onboarding stage. The profession enum values are grouped
 * into 5 archetypes; each archetype owns two scripts (one per platform)
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
  engineering: "builder",
  product: "builder",

  executive: "operator",
  sales: "operator",
  marketing: "operator",
  finance: "operator",

  founder: "founder",

  student: "scholar",

  creative: "default",
  other: "default",
};

const PREVIEW_PLATFORMS: ReadonlySet<string> = new Set<PlatformPreviewPlatform>(
  ["telegram", "whatsapp", "imessage"],
);

/** Whether a platform has a preview script. */
export function isPreviewPlatform(
  platform: string,
): platform is PlatformPreviewPlatform {
  return PREVIEW_PLATFORMS.has(platform);
}

export function getArchetype(
  profession: string | undefined,
): ProfessionArchetype {
  if (!profession) return "default";
  return PROFESSION_TO_ARCHETYPE[profession.toLowerCase()] ?? "default";
}

type ArchetypeScripts = Record<PlatformPreviewPlatform, PlatformScript>;

export const PLATFORM_PREVIEW_ORDER: PlatformPreviewPlatform[] = [
  "telegram",
  "whatsapp",
  "imessage",
];

export const PLATFORM_LABELS: Record<PlatformPreviewPlatform, string> = {
  telegram: "Telegram",
  whatsapp: "WhatsApp",
  imessage: "iMessage",
};

export const PLATFORM_ICONS: Record<PlatformPreviewPlatform, string> = {
  telegram: "/images/icons/macos/telegram.webp",
  whatsapp: "/images/icons/macos/whatsapp.webp",
  imessage: "/images/icons/macos/imessage.webp",
};

const USER_PLACEHOLDER_NAME = "__user__";
const USER_PLACEHOLDER_AVATAR = "__user_avatar__";
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
  imessage: {
    title: "GAIA",
    messages: [
      {
        from: "them",
        text: "Heads up: the deploy you kicked off last night finished clean. Zero errors in the logs.",
        time: "7:52",
      },
      {
        from: "them",
        text: "Two PRs are waiting on your review. I summarised both, the second one touches auth.",
        time: "7:52",
      },
      {
        from: "me",
        text: "move standup to 10, I want to read the auth one first",
        time: "7:55",
        status: "read",
      },
      {
        from: "them",
        text: "Done. Standup is at 10, the team has the new invite.",
        time: "7:55",
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
  imessage: {
    title: "GAIA",
    messages: [
      {
        from: "them",
        text: "Morning. Three things need you today, the rest I handled.",
        time: "8:05",
      },
      {
        from: "them",
        text: "The Q3 forecast deck is due at 2. I pulled the numbers from the sheet and drafted the summary slide.",
        time: "8:05",
      },
      {
        from: "me",
        text: "who's the 11am with again?",
        time: "8:09",
        status: "read",
      },
      {
        from: "them",
        text: "Priya from Northwind, renewal call. Her last email asked about the new pricing, brief is in your calendar.",
        time: "8:09",
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
  imessage: {
    title: "GAIA",
    messages: [
      {
        from: "them",
        text: "Your investor update draft is ready, built from this week's numbers. Want to read it before it goes?",
        time: "9:10",
      },
      {
        from: "me",
        text: "yes, and chase the two candidates who went quiet",
        time: "9:12",
        status: "read",
      },
      {
        from: "them",
        text: "Read it in the doc. Both candidates chased, one already replied: she can do Thursday.",
        time: "9:12",
      },
      { from: "me", text: "book her", time: "9:14", status: "read" },
      {
        from: "them",
        text: "Booked, Thursday 3pm, invite sent.",
        time: "9:14",
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
  imessage: {
    title: "GAIA",
    messages: [
      {
        from: "them",
        text: "Lecture moved to room 204. Your reading for it is summarised, the two key papers are up top.",
        time: "8:30",
      },
      {
        from: "me",
        text: "when is the essay due again",
        time: "8:31",
        status: "read",
      },
      {
        from: "them",
        text: "Friday, 5pm. Outline is drafted from your notes, want it in the doc?",
        time: "8:31",
      },
      { from: "me", text: "yes please", time: "8:32", status: "read" },
      {
        from: "them",
        text: "In the doc. Reminder set for Thursday morning.",
        time: "8:32",
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
  imessage: {
    title: "GAIA",
    messages: [
      {
        from: "them",
        text: "Morning. Your inbox is sorted, two emails need a reply from you and I drafted both.",
        time: "8:15",
      },
      { from: "me", text: "what's on today?", time: "8:17", status: "read" },
      {
        from: "them",
        text: "Dentist at 11, call with Sam at 3. Sam wants the proposal first, it's attached to the invite.",
        time: "8:17",
      },
      {
        from: "me",
        text: "great, send the proposal now",
        time: "8:18",
        status: "read",
      },
      {
        from: "them",
        text: "Sent. I'll nudge you before the call.",
        time: "8:18",
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
