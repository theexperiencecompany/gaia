import { nextFriday, setHours, startOfHour } from "date-fns";

import type { TaskEnds, TaskWatch } from "./taskModel";
import { DEADLINE_HOUR, freshExpiry, needsSecondRead } from "./watchModel";

/**
 * Stand-ins for GAIA reading a sentence and doing its first check. The real call
 * compiles the sentence to a typed watch and reads the source once before saving;
 * these return what it returns, for a few sentences, after a believable wait.
 */

/** How long the first check takes in the demo. */
export const CHECK_MS = 1400;

/** What reading a sentence gives back: a watch to confirm, one question, or a first check that failed. */
export type SentenceRead =
  | { kind: "proposal"; watch: TaskWatch; ends?: TaskEnds }
  | { kind: "question"; question: string }
  | { kind: "failed"; line: string };

type Draft = Omit<
  TaskWatch,
  "sentence" | "confirmTwice" | "expiresAt" | "alerts" | "reading"
> & {
  reading: string;
  ends?: TaskEnds;
};

const ONCE: TaskEnds = { afterRuns: 1 };

const friday = () =>
  setHours(startOfHour(nextFriday(new Date())), DEADLINE_HOUR).toISOString();

/** Each canned sentence, by a word it must contain, and what GAIA makes of it. */
const PROPOSALS: { words: string[]; draft: () => Draft }[] = [
  {
    words: ["billy", "bookcase"],
    draft: () => ({
      kind: "threshold",
      source: { rung: "page", site: "ikea.com", label: "Billy bookcase" },
      condition: { direction: "below", value: 50, unit: "$" },
      reading: "$59",
      everyMinutes: 60,
      ends: ONCE,
    }),
  },
  {
    words: ["bitcoin"],
    draft: () => ({
      kind: "threshold",
      source: { rung: "api", site: "coingecko.com", label: "Bitcoin" },
      condition: { direction: "above", value: 150000, unit: "$" },
      reading: "$97,412",
      everyMinutes: 15,
      ends: ONCE,
    }),
  },
  {
    words: ["hacker news", "hn"],
    draft: () => ({
      kind: "new_items",
      source: {
        rung: "api",
        site: "news.ycombinator.com",
        label: "Hacker News",
      },
      condition: { items: "New posts about GAIA" },
      reading: "Nothing new since you asked",
      everyMinutes: 15,
    }),
  },
  {
    words: ["down", "uptime"],
    draft: () => ({
      kind: "uptime",
      source: { rung: "page", site: "northwind.co", label: "northwind.co" },
      condition: {},
      reading: "Up",
      everyMinutes: 1,
    }),
  },
  {
    words: ["ai 101", "air india"],
    draft: () => ({
      kind: "state",
      source: {
        rung: "api",
        site: "flightaware.com",
        label: "AI 101 on Dec 3",
      },
      condition: {
        target: "Delayed",
        states: ["Delayed", "Cancelled", "Any change"],
        finalStates: ["Landed", "Cancelled"],
      },
      reading: "On time",
      everyMinutes: 15,
    }),
  },
  {
    words: ["reply", "replied", "hear back"],
    draft: () => ({
      kind: "reply_by",
      source: { rung: "connector", app: "gmail", label: "Kenji's thread" },
      condition: { from: "Kenji", deadline: friday() },
      reading: "No reply yet",
      everyMinutes: 15,
      ends: ONCE,
    }),
  },
];

/** A sentence that leaves out what to watch: GAIA asks one plain question. */
const QUESTIONS: { words: string[]; question: string }[] = [
  { words: ["flight"], question: "Which flight? Airline, number and date." },
];

/** A sentence whose source turned GAIA away on the first check. */
const FAILS: { words: string[]; line: string }[] = [
  {
    words: ["best buy", "ps6"],
    line: "Best Buy turned GAIA away, so it can't see the stock right now. GAIA only sets up a watch it can see.",
  },
];

const has = (sentence: string, words: string[]) =>
  words.some((word) => sentence.includes(word));

function proposal(sentence: string, draft: Draft): SentenceRead {
  const { reading, ends, ...rest } = draft;
  return {
    kind: "proposal",
    ends,
    watch: {
      ...rest,
      sentence,
      confirmTwice: needsSecondRead(rest),
      expiresAt: freshExpiry(),
      alerts: 0,
      reading: { value: reading, at: new Date().toISOString() },
    },
  };
}

/** Anything else has no single source: GAIA looks once a day and tells you when it finds it. */
export function lookDaily(sentence: string): SentenceRead {
  return proposal(sentence, {
    kind: "open",
    source: { rung: "agent", label: asLabel(sentence) },
    condition: {},
    reading: "Not yet",
    everyMinutes: 1440,
    ends: ONCE,
  });
}

/** The sentence as a label: its "tell me when" lead dropped, capitalised. */
function asLabel(sentence: string): string {
  const core = sentence
    .trim()
    .replace(
      /^(tell me|let me know|ping me|alert me|notify me)\s+(when|if)\s+/i,
      "",
    )
    .replace(/[.?!]+$/, "");
  return core.charAt(0).toUpperCase() + core.slice(1);
}

/** Read a sentence (and the answer to GAIA's question, if it asked one) the way the real call does. */
export function readSentence(sentence: string, answer?: string): SentenceRead {
  const text = `${sentence} ${answer ?? ""}`.toLowerCase();
  const fail = FAILS.find((item) => has(text, item.words));
  if (fail) return { kind: "failed", line: fail.line };
  const known = PROPOSALS.find((item) => has(text, item.words));
  if (known) return proposal(sentence, known.draft());
  const asks = QUESTIONS.find((item) => has(text, item.words));
  if (asks && !answer) return { kind: "question", question: asks.question };
  return lookDaily(sentence);
}

/** The empty sentence field's example. */
export const EXAMPLE = "The Billy bookcase at IKEA drops under $50";
