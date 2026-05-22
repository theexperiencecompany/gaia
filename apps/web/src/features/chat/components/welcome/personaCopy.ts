/**
 * Persona-specific welcome copy rendered as the single post-onboarding bot
 * message. Each entry is one string with `<NEW_MESSAGE_BREAK>` splits — the
 * shared bot bubble renderer staggers each segment into its own bubble.
 *
 * Keys are the canonical `profession` values from `professionOptions` in
 * `apps/web/src/features/onboarding/constants/index.ts`. Direct lookup, no
 * fuzzy matching — anything missing falls through to `FALLBACK_COPY`.
 */

const GREETING = "Hey, welcome! I'm your GAIA (general-purpose ai assistant).";

interface PersonaEntry {
  middle: string;
  close: string;
}

const ENTRIES: Record<string, PersonaEntry> = {
  developer: {
    middle:
      "I can triage your open PRs, prep your standup notes, and summarize the Slack threads you've been ignoring.",
    close: "Just connect GitHub and Linear and I'll get to it!",
  },
  engineer: {
    middle:
      "I can triage your open PRs, prep your standup notes, and summarize the Slack threads you've been ignoring.",
    close: "Just connect GitHub and Linear and I'll get to it!",
  },
  designer: {
    middle:
      "I can draft client check-ins, turn loose feedback into todos, and call out projects gathering dust.",
    close: "Just connect Notion and Slack and I'll get to it!",
  },
  artist: {
    middle:
      "I can draft client check-ins, turn loose feedback into todos, and call out projects gathering dust.",
    close: "Just connect Notion and Slack and I'll get to it!",
  },
  manager: {
    middle:
      "I can write your weekly status updates, prep standups from yesterday's threads, and call out work that's slipping.",
    close: "Just connect Linear and Slack and I'll get to it!",
  },
  analyst: {
    middle:
      "I can write your weekly status updates, prep standups from yesterday's threads, and call out work that's slipping.",
    close: "Just connect Linear and Slack and I'll get to it!",
  },
  consultant: {
    middle:
      "I can write your weekly status updates, prep standups from yesterday's threads, and call out work that's slipping.",
    close: "Just connect Linear and Slack and I'll get to it!",
  },
  entrepreneur: {
    middle:
      "I can draft investor updates, prep your meeting notes, and pull together what needs your attention this week.",
    close: "Just connect Calendar and Notion and I'll get to it!",
  },
  researcher: {
    middle:
      "I can rank your drafts by readiness, pull research when you're stuck, and resurface notes you forgot you wrote.",
    close: "Just connect Notion and Google Docs and I'll get to it!",
  },
  writer: {
    middle:
      "I can rank your drafts by readiness, pull research when you're stuck, and resurface notes you forgot you wrote.",
    close: "Just connect Notion and Google Docs and I'll get to it!",
  },
  marketing: {
    middle:
      "I can draft follow-ups in your voice, surface deals waiting on you, and watch competitor moves while you sleep.",
    close: "Just connect HubSpot and Notion and I'll get to it!",
  },
  sales: {
    middle:
      "I can draft follow-ups in your voice, surface deals waiting on you, and watch competitor moves while you sleep.",
    close: "Just connect HubSpot and Notion and I'll get to it!",
  },
  student: {
    middle:
      "I can flag upcoming deadlines, draft your weekly study plan, and summarize the readings you haven't opened.",
    close: "Just connect Calendar and Notion and I'll get to it!",
  },
  teacher: {
    middle:
      "I can draft lesson plans, summarize student emails, and tell you what needs grading first.",
    close: "Just connect Calendar and Google Docs and I'll get to it!",
  },
  doctor: {
    middle:
      "I can prep for tomorrow's meetings, summarize long client threads, and flag anything overdue before it bites.",
    close: "Just connect Calendar and Gmail and I'll get to it!",
  },
  lawyer: {
    middle:
      "I can prep for tomorrow's meetings, summarize long client threads, and flag anything overdue before it bites.",
    close: "Just connect Calendar and Gmail and I'll get to it!",
  },
  accountant: {
    middle:
      "I can prep for tomorrow's meetings, summarize long client threads, and flag anything overdue before it bites.",
    close: "Just connect Calendar and Gmail and I'll get to it!",
  },
  freelancer: {
    middle:
      "I can triage client requests, draft updates in your voice, and flag invoices that are slipping.",
    close: "Just connect Calendar and Gmail and I'll get to it!",
  },
};

const FALLBACK: PersonaEntry = {
  middle:
    "I can draft messages, prep your week, and surface things that need your attention.",
  close: "Just connect a few tools and I'll get to it!",
};

function build({ middle, close }: PersonaEntry): string {
  return `${GREETING}<NEW_MESSAGE_BREAK>${middle}<NEW_MESSAGE_BREAK>${close}`;
}

export function getWelcomeCopyForProfession(
  profession: string | null | undefined,
): string {
  if (!profession) return build(FALLBACK);
  const entry = ENTRIES[profession];
  return entry ? build(entry) : build(FALLBACK);
}
