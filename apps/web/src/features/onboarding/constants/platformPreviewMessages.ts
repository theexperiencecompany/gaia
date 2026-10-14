/**
 * Profession-keyed message scripts for the platform preview shown in the
 * `platformPick` onboarding stage. One script set per profession value from
 * question one (the same value the wizard stores), three scripts each, one per
 * platform. Every script demonstrates the three things the copy promises:
 * morning briefings, urgent email flags, and workflow-finished pings, and
 * GAIA addresses the user by first name where the account has one.
 *
 * Rewrite scripts here; the preview component is data-driven and has no
 * other coupling to profession.
 */

import type { ChatMessageItem } from "@/features/landing/components/iphone/ChatDemo";
import type {
  PlatformPreviewPlatform,
  PlatformScript,
  UserIdentity,
} from "./platformPreviewMessages.types";

export type {
  PlatformPreviewPlatform,
  PlatformScript,
  UserIdentity,
} from "./platformPreviewMessages.types";

type PlatformScripts = Record<PlatformPreviewPlatform, PlatformScript>;

/** One chat bubble as written: who sent it, the copy, the clock, and — for the
 *  user's own lines — the delivery receipt. */
type ScriptLine = readonly [
  from: NonNullable<ChatMessageItem["from"]>,
  text: string,
  time: string,
  status?: NonNullable<ChatMessageItem["status"]>,
];

function script(
  title: string,
  lines: readonly ScriptLine[],
  subtitle?: string,
): PlatformScript {
  const messages: ChatMessageItem[] = lines.map(([from, text, time, status]) =>
    status === undefined ? { from, text, time } : { from, text, time, status },
  );
  return subtitle === undefined
    ? { title, messages }
    : { title, messages, subtitle };
}

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

/** The `professionOptions` values; a typed-in job falls back to `other`. */
export const PROFESSION_SCRIPT_KEYS = [
  "founder",
  "executive",
  "sales",
  "product",
  "creative",
  "engineering",
  "marketing",
  "finance",
  "student",
  "other",
] as const;
export type ProfessionScriptKey = (typeof PROFESSION_SCRIPT_KEYS)[number];

/** GAIA's lines carry this token; it always follows a word, so dropping it for
 *  an account with no first name leaves a natural sentence behind. */
const NAME_TOKEN = "{name}";

export function isPreviewPlatform(
  platform: string,
): platform is PlatformPreviewPlatform {
  return PLATFORM_PREVIEW_ORDER.includes(platform as PlatformPreviewPlatform);
}

function toScriptKey(profession: string | undefined): ProfessionScriptKey {
  return PROFESSION_SCRIPT_KEYS.includes(profession as ProfessionScriptKey)
    ? (profession as ProfessionScriptKey)
    : "other";
}

function personalize(text: string, firstName: string | undefined): string {
  return firstName
    ? text.replaceAll(NAME_TOKEN, firstName)
    : text.replaceAll(` ${NAME_TOKEN}`, "");
}

const FOUNDER_SCRIPTS: PlatformScripts = {
  telegram: script(
    "GAIA",
    [
      [
        "them",
        "morning {name}! inbox is sorted, 3 investor replies drafted and waiting for your ok.",
        "8:12",
      ],
      [
        "them",
        "also the board deck is due friday. i pulled last month's numbers into the template already.",
        "8:12",
      ],
      ["me", "anything from the seed lead?", "8:14", "read"],
      [
        "them",
        "yep, she asked for the updated runway. i attached it to the draft, just hit send.",
        "8:14",
      ],
    ],
    "bot",
  ),
  whatsapp: script("GAIA", [
    [
      "them",
      "Heads up {name}, your 2pm with the hiring candidate moved to 3. I updated the invite.",
      "9:05",
    ],
    ["them", "Two team standups have no notes yet. Want me to chase?", "9:05"],
    [
      "me",
      "chase them, and remind me to send the offer letter",
      "9:07",
      "read",
    ],
    [
      "them",
      "Done. Both pinged, and I'll remind you at 4 about the offer.",
      "9:07",
    ],
  ]),
  imessage: script("GAIA", [
    [
      "them",
      "Morning {name}. Runway update is ready, MRR is up 6% on last month.",
      "7:48",
    ],
    [
      "them",
      "Your competitor shipped pricing changes overnight. One-paragraph summary is in your inbox.",
      "7:48",
    ],
    ["me", "book 20 min with Priya to go over it", "7:51", "read"],
    ["them", "Booked for 11:30. She has the summary too.", "7:51"],
  ]),
};

const EXECUTIVE_SCRIPTS: PlatformScripts = {
  telegram: script(
    "GAIA",
    [
      [
        "them",
        "morning {name}! 3 reports landed overnight, i read them so you don't have to. one decision needs you.",
        "7:55",
      ],
      [
        "them",
        "ops wants a yes or no on the vendor contract by noon. the two options are in your inbox, side by side.",
        "7:55",
      ],
      ["me", "go with option B, tell them", "7:58", "read"],
      ["them", "sent {name}. contract's on its way for signature.", "7:58"],
    ],
    "bot",
  ),
  whatsapp: script("GAIA", [
    [
      "them",
      "Heads up {name}, the board pre-read got 4 comments. I summarised them, two are quick fixes.",
      "8:20",
    ],
    ["them", "Your 10am and 10:30 overlap. Move the 10:30?", "8:20"],
    ["me", "yes, and draft a reply to the CFO's comment", "8:22", "read"],
    [
      "them",
      "Moved to 11. Draft's in your inbox, tone matches your last reply to him.",
      "8:22",
    ],
  ]),
  imessage: script("GAIA", [
    [
      "them",
      "Morning {name}. Today: leadership sync at 9, two 1:1s, investor dinner at 7.",
      "7:30",
    ],
    [
      "them",
      "The Q3 numbers you asked for are in the sync invite. Revenue beat plan by 4%.",
      "7:30",
    ],
    ["me", "cancel the 3pm, I need thinking time", "7:33", "read"],
    [
      "them",
      "Cancelled and rescheduled for Thursday. Your afternoon is clear.",
      "7:33",
    ],
  ]),
};

const SALES_SCRIPTS: PlatformScripts = {
  telegram: script(
    "GAIA",
    [
      [
        "them",
        "morning {name}! 2 leads went quiet this week. i drafted follow-ups for both, warm not pushy.",
        "8:05",
      ],
      [
        "them",
        "your 11am call is with Nadia at Northwind. she just raised a series A, i put the details in your brief.",
        "8:05",
      ],
      ["me", "send both follow-ups", "8:07", "read"],
      ["them", "sent. i'll flag you the second either one replies.", "8:07"],
    ],
    "bot",
  ),
  whatsapp: script("GAIA", [
    [
      "them",
      "Heads up {name}, the Acme proposal was opened 3 times last night. They're reading it.",
      "9:10",
    ],
    [
      "them",
      "Their CTO also joined the deal thread. I pulled his background into your call notes.",
      "9:10",
    ],
    ["me", "book a demo with them for tomorrow", "9:12", "read"],
    [
      "them",
      "Sent them three slots. I'll confirm the moment they pick one.",
      "9:12",
    ],
  ]),
  imessage: script("GAIA", [
    [
      "them",
      "Morning {name}. Pipeline is at 82% of quota, two deals could close this week.",
      "7:45",
    ],
    [
      "them",
      "Call research is done for all 4 meetings today. Each brief is one screen.",
      "7:45",
    ],
    ["me", "move the Lumen call to after lunch", "7:48", "read"],
    ["them", "Moved to 2:15. Their side accepted already.", "7:48"],
  ]),
};

const PRODUCT_SCRIPTS: PlatformScripts = {
  telegram: script(
    "GAIA",
    [
      [
        "them",
        "morning {name}! 14 pieces of feedback came in overnight. 3 are the same onboarding bug, i grouped them.",
        "8:20",
      ],
      [
        "them",
        "the spec for the export feature is drafted from your notes. it's in the doc, needs your eyes on scope.",
        "8:20",
      ],
      ["me", "file the onboarding bug and tag it high", "8:22", "read"],
      [
        "them",
        "filed and tagged. eng lead is on it, i'll tell you when it ships.",
        "8:22",
      ],
    ],
    "bot",
  ),
  whatsapp: script("GAIA", [
    [
      "them",
      "Heads up {name}, design posted the new checkout flow. Two comments from support are worth a look.",
      "9:00",
    ],
    [
      "them",
      "Your roadmap review is at 2, I put the updated numbers in the invite.",
      "9:00",
    ],
    ["me", "summarise the support comments for the review", "9:03", "read"],
    ["them", "Done, one paragraph each, added to the invite.", "9:03"],
  ]),
  imessage: script("GAIA", [
    [
      "them",
      "Morning {name}. Feature adoption is up 12% since the release. Three users asked for the same thing.",
      "7:50",
    ],
    [
      "them",
      "Your customer interview is at 11. I wrote the questions from last week's gaps.",
      "7:50",
    ],
    ["me", "send the questions to Dev before the call", "7:53", "read"],
    ["them", "Sent. He's reviewed them and added one.", "7:53"],
  ]),
};

const CREATIVE_SCRIPTS: PlatformScripts = {
  telegram: script(
    "GAIA",
    [
      [
        "them",
        "morning {name}! 2 clients replied on the brand deck. one loves it, one wants the type bigger.",
        "8:30",
      ],
      [
        "them",
        "your client call moved to 3. that gives you the whole morning to make.",
        "8:30",
      ],
      ["me", "send the type feedback to the print shop", "8:32", "read"],
      ["them", "sent {name}. they'll have a proof by tomorrow.", "8:32"],
    ],
    "bot",
  ),
  whatsapp: script("GAIA", [
    [
      "them",
      "Heads up {name}, the invoice from March finally got paid. I logged it.",
      "9:15",
    ],
    [
      "them",
      "New inquiry came in, a podcast wants cover art. Budget looks right for you.",
      "9:15",
    ],
    ["me", "reply that I can start next week", "9:17", "read"],
    [
      "them",
      "Replied, with your usual rate and next Tuesday as the start.",
      "9:17",
    ],
  ]),
  imessage: script("GAIA", [
    [
      "them",
      "Morning {name}. Your portfolio got 40 new visits from that post yesterday.",
      "7:55",
    ],
    [
      "them",
      "Two references you saved this week are in a folder called moodboard, ready for the pitch.",
      "7:55",
    ],
    ["me", "block tomorrow morning for deep work", "7:58", "read"],
    ["them", "Blocked 9 to 1. No meetings can land there now.", "7:58"],
  ]),
};

const ENGINEERING_SCRIPTS: PlatformScripts = {
  telegram: script(
    "GAIA",
    [
      [
        "them",
        "morning {name}! pushed your 9am standup back to 10 so you've got a bit more breathing room.",
        "8:40",
      ],
      [
        "them",
        "2 code reviews are waiting on you, and last night's deploy went through fine.",
        "8:40",
      ],
      ["me", "anything actually on fire?", "8:41", "read"],
      ["them", "nope, all quiet. go grab your coffee first.", "8:41"],
    ],
    "bot",
  ),
  whatsapp: script("GAIA", [
    [
      "them",
      "Heads up {name}, your tech lead replied on the migration thread. She wants a call today.",
      "9:05",
    ],
    [
      "them",
      "The flaky test you muted is failing on main again. I opened an issue with the last 3 runs.",
      "9:05",
    ],
    ["me", "book 15 min with her after lunch", "9:07", "read"],
    [
      "them",
      "Booked 1:30. The thread and the issue are in the invite.",
      "9:07",
    ],
  ]),
  imessage: script("GAIA", [
    [
      "them",
      "Morning {name}. The deploy you kicked off last night finished clean, zero errors.",
      "7:52",
    ],
    [
      "them",
      "Two PRs are waiting on your review. I summarised both, the second one touches auth.",
      "7:52",
    ],
    [
      "me",
      "move standup to 10, I want to read the auth one first",
      "7:55",
      "read",
    ],
    ["them", "Done. Standup is at 10, the team has the new invite.", "7:55"],
  ]),
};

const MARKETING_SCRIPTS: PlatformScripts = {
  telegram: script(
    "GAIA",
    [
      [
        "them",
        "morning {name}! yesterday's campaign email got a 31% open rate, best this quarter.",
        "8:15",
      ],
      [
        "them",
        "3 people replied asking about pricing. i drafted replies and looped in sales on one.",
        "8:15",
      ],
      ["me", "what's the plan for the launch post?", "8:17", "read"],
      [
        "them",
        "draft's ready, i pulled the 3 strongest customer quotes in. want it in your inbox?",
        "8:17",
      ],
    ],
    "bot",
  ),
  whatsapp: script("GAIA", [
    [
      "them",
      "Heads up {name}, the agency sent the new landing page copy. Two headlines to pick from.",
      "9:20",
    ],
    [
      "them",
      "Your content review moved to 4. Everything for it is in the invite.",
      "9:20",
    ],
    ["me", "go with the second headline", "9:22", "read"],
    ["them", "Told them. They'll have the page live by Thursday.", "9:22"],
  ]),
  imessage: script("GAIA", [
    [
      "them",
      "Morning {name}. Weekly numbers are in: traffic up 9%, signups flat, one post did most of the work.",
      "7:40",
    ],
    [
      "them",
      "A journalist asked for a quote by noon. I drafted one in your voice.",
      "7:40",
    ],
    [
      "me",
      "send the quote, and schedule the recap post for 10",
      "7:43",
      "read",
    ],
    [
      "them",
      "Quote sent, recap scheduled for 10. I'll share the reach at 5.",
      "7:43",
    ],
  ]),
};

const FINANCE_SCRIPTS: PlatformScripts = {
  telegram: script(
    "GAIA",
    [
      [
        "them",
        "morning {name}! month-end close is 80% there. 4 invoices are still missing receipts, i chased all four.",
        "8:00",
      ],
      [
        "them",
        "the FX move overnight shifts the forecast by about 2%. updated sheet is in your inbox.",
        "8:00",
      ],
      ["me", "which invoices?", "8:02", "read"],
      [
        "them",
        "two from travel, two from the design agency. i'll ping you when they land.",
        "8:02",
      ],
    ],
    "bot",
  ),
  whatsapp: script("GAIA", [
    [
      "them",
      "Heads up {name}, the auditor asked for the Q2 reconciliation. I found it and replied with the file.",
      "9:30",
    ],
    [
      "them",
      "Your budget review is at 2. Variance summary is in the invite, two lines need a comment.",
      "9:30",
    ],
    ["me", "draft the comments from last month's notes", "9:32", "read"],
    ["them", "Drafted both, they're in the sheet next to the numbers.", "9:32"],
  ]),
  imessage: script("GAIA", [
    [
      "them",
      "Morning {name}. Cash position is steady, runway is 19 months on current burn.",
      "7:35",
    ],
    [
      "them",
      "Payroll is queued for Friday. One new starter is missing bank details, I've asked HR.",
      "7:35",
    ],
    ["me", "remind me to approve payroll thursday morning", "7:38", "read"],
    ["them", "Set for Thursday 9am. I'll include the final total.", "7:38"],
  ]),
};

const STUDENT_SCRIPTS: PlatformScripts = {
  telegram: script(
    "GAIA",
    [
      [
        "them",
        "morning {name}! your essay draft is due thursday. i pulled the 5 sources you saved into one outline.",
        "8:25",
      ],
      [
        "them",
        "lecture at 10 moved rooms, it's in the science block now. calendar's updated.",
        "8:25",
      ],
      ["me", "what's due this week?", "8:27", "read"],
      [
        "them",
        "essay thursday, problem set friday. i blocked 2 hours tomorrow for the problem set.",
        "8:27",
      ],
    ],
    "bot",
  ),
  whatsapp: script("GAIA", [
    [
      "them",
      "Heads up {name}, your professor replied about the extension. Yes, until Monday.",
      "9:40",
    ],
    [
      "them",
      "Your group chat picked Wednesday 6pm for the project. I added it to your calendar.",
      "9:40",
    ],
    ["me", "remind me to email the internship people tonight", "9:42", "read"],
    [
      "them",
      "Reminder set for 8pm, with the draft you wrote last week attached.",
      "9:42",
    ],
  ]),
  imessage: script("GAIA", [
    [
      "them",
      "Morning {name}. Three lectures today, one quiz at 2. Your notes from last week are summarised.",
      "7:45",
    ],
    [
      "them",
      "The library book you need is available again. Want me to reserve it?",
      "7:45",
    ],
    ["me", "yes, and block friday afternoon to study", "7:48", "read"],
    [
      "them",
      "Reserved, and Friday 1 to 5 is blocked. No one can book over it.",
      "7:48",
    ],
  ]),
};

const OTHER_SCRIPTS: PlatformScripts = {
  telegram: script(
    "GAIA",
    [
      [
        "them",
        "morning {name}! inbox is sorted, 2 emails need a reply from you and i drafted both.",
        "8:15",
      ],
      [
        "them",
        "dentist at 11, call with Sam at 3. Sam wants the proposal first, it's attached to the invite.",
        "8:15",
      ],
      ["me", "send the proposal now", "8:17", "read"],
      ["them", "sent. i'll nudge you before the call.", "8:17"],
    ],
    "bot",
  ),
  whatsapp: script("GAIA", [
    [
      "them",
      "Heads up {name}, your 3pm moved to 4. I updated the invite and told Sam.",
      "9:25",
    ],
    [
      "them",
      "The form you were waiting on came back signed. It's filed.",
      "9:25",
    ],
    ["me", "remind me to call the bank tomorrow", "9:27", "read"],
    [
      "them",
      "Reminder set for 10am tomorrow, with the account number in it.",
      "9:27",
    ],
  ]),
  imessage: script("GAIA", [
    [
      "them",
      "Morning {name}. Two things need you today, the rest I handled.",
      "7:50",
    ],
    [
      "them",
      "Your package arrives between 2 and 4. I'll ping you when it's at the door.",
      "7:50",
    ],
    ["me", "move my 2pm so I'm home for it", "7:53", "read"],
    ["them", "Moved to 11. You're free from 2.", "7:53"],
  ]),
};

const PROFESSION_SCRIPTS: Record<ProfessionScriptKey, PlatformScripts> = {
  founder: FOUNDER_SCRIPTS,
  executive: EXECUTIVE_SCRIPTS,
  sales: SALES_SCRIPTS,
  product: PRODUCT_SCRIPTS,
  creative: CREATIVE_SCRIPTS,
  engineering: ENGINEERING_SCRIPTS,
  marketing: MARKETING_SCRIPTS,
  finance: FINANCE_SCRIPTS,
  student: STUDENT_SCRIPTS,
  other: OTHER_SCRIPTS,
};

export function getPlatformScript(
  profession: string | undefined,
  platform: PlatformPreviewPlatform,
  user: UserIdentity = { firstName: undefined },
): PlatformScript {
  const raw = PROFESSION_SCRIPTS[toScriptKey(profession)][platform];
  return {
    ...raw,
    messages: raw.messages.map((m) =>
      m.from === "them" && m.text
        ? { ...m, text: personalize(m.text, user.firstName) }
        : m,
    ),
  };
}
