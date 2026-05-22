import { Priority } from "../types/todo";
import type {
  QuickAddOptions,
  QuickAddProject,
  QuickAddProjectMatch,
  QuickAddResult,
} from "./quickAdd.types";

export type {
  QuickAddOptions,
  QuickAddProject,
  QuickAddProjectMatch,
  QuickAddResult,
} from "./quickAdd.types";

/**
 * A pure quick-add parser that mirrors the rules used by the web client's
 * `useTextProcessor` hook so that web and mobile share a single source of
 * truth.
 *
 * Tokens recognised (each requires a trailing whitespace to be considered a
 * complete token, matching the web behaviour where in-progress typing must
 * not flicker out from under the user):
 *  - `@projectname ` (case-insensitive). Attempts to match against the
 *    supplied `projects` list; falls back to a free-form name if none match.
 *  - `#labelname ` — multiple allowed.
 *  - Priority: `p1`/`p2`/`p3` first; otherwise `high|urgent|important`,
 *    `medium|normal`, `low`. First match wins.
 *  - Date tokens: `today`, `tomorrow`, `yesterday`, `in N days`, `next week`,
 *    `this weekend`, `next monday` (and other day names).
 */

const DAY_MS = 86_400_000;

const WEEKDAY_NAMES = [
  "sunday",
  "monday",
  "tuesday",
  "wednesday",
  "thursday",
  "friday",
  "saturday",
] as const;

function addDays(date: Date, days: number): Date {
  return new Date(date.getTime() + days * DAY_MS);
}

function resolveProject(
  raw: string,
  projects: QuickAddProject[] | undefined,
): QuickAddProjectMatch {
  const lookup = raw.toLowerCase();
  const match = projects?.find((p) => {
    const name = p.name.toLowerCase();
    return name === lookup || name.includes(lookup) || lookup.includes(name);
  });
  if (match) return { id: match.id, name: match.name };
  return { name: raw };
}

function detectTimezone(override: string | undefined): string | undefined {
  if (override) return override;
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone;
  } catch {
    return undefined;
  }
}

export function parseQuickAdd(
  input: string,
  options: QuickAddOptions = {},
): QuickAddResult {
  const result: QuickAddResult = {
    cleanedText: "",
    labels: [],
    dueDate: null,
  };

  if (!input) return result;

  const projects = options.projects;
  const now = options.now ?? new Date();
  const timezone = detectTimezone(options.timezone);
  if (timezone) result.timezone = timezone;

  let cleaned = input;

  // Project: @name<space>
  const projectMatches = cleaned.match(/@([a-zA-Z0-9_-]+)\s/g);
  if (projectMatches) {
    for (const match of projectMatches) {
      const raw = match.slice(1, -1);
      result.project = resolveProject(raw, projects);
      cleaned = cleaned.replace(match, " ");
    }
  }

  // Labels: #name<space> (multiple)
  const labelMatches = cleaned.match(/#([a-zA-Z0-9_-]+)\s/g);
  if (labelMatches) {
    result.labels = labelMatches.map((m) => m.slice(1, -1));
    for (const match of labelMatches) {
      cleaned = cleaned.replace(match, " ");
    }
  }

  // Priority: p1/p2/p3 first
  const priorityNumMatch = cleaned.match(/\bp([123])\b/i);
  if (priorityNumMatch) {
    const num = priorityNumMatch[1];
    result.priority =
      num === "1"
        ? Priority.HIGH
        : num === "2"
          ? Priority.MEDIUM
          : Priority.LOW;
    cleaned = cleaned.replace(priorityNumMatch[0], " ");
  } else {
    const priorityWordMatch = cleaned.match(
      /\b(high|urgent|important|medium|normal|low)\b/i,
    );
    if (priorityWordMatch) {
      const word = priorityWordMatch[1].toLowerCase();
      result.priority =
        word === "high" || word === "urgent" || word === "important"
          ? Priority.HIGH
          : word === "medium" || word === "normal"
            ? Priority.MEDIUM
            : Priority.LOW;
      cleaned = cleaned.replace(priorityWordMatch[0], " ");
    }
  }

  // Date tokens — order matches the web parser. Last match wins because each
  // assignment overwrites `dueDate`.
  const todayMatch = cleaned.match(/\btoday\b/i);
  if (todayMatch) {
    result.dueDate = new Date(now);
    cleaned = cleaned.replace(todayMatch[0], " ");
  }

  const tomorrowMatch = cleaned.match(/\btomorrow\b/i);
  if (tomorrowMatch) {
    result.dueDate = addDays(now, 1);
    cleaned = cleaned.replace(tomorrowMatch[0], " ");
  }

  const yesterdayMatch = cleaned.match(/\byesterday\b/i);
  if (yesterdayMatch) {
    result.dueDate = addDays(now, -1);
    cleaned = cleaned.replace(yesterdayMatch[0], " ");
  }

  const inDaysMatch = cleaned.match(/\bin\s+(\d+)\s+days?\b/i);
  if (inDaysMatch) {
    const days = Number.parseInt(inDaysMatch[1], 10);
    if (!Number.isNaN(days)) {
      result.dueDate = addDays(now, days);
    }
    cleaned = cleaned.replace(inDaysMatch[0], " ");
  }

  const nextWeekMatch = cleaned.match(/\bnext\s+week\b/i);
  if (nextWeekMatch) {
    result.dueDate = addDays(now, 7);
    cleaned = cleaned.replace(nextWeekMatch[0], " ");
  }

  const weekendMatch = cleaned.match(/\bthis\s+weekend\b/i);
  if (weekendMatch) {
    const dayOfWeek = now.getDay();
    const daysUntilSaturday = (6 - dayOfWeek + 7) % 7;
    result.dueDate = addDays(now, daysUntilSaturday || 7);
    cleaned = cleaned.replace(weekendMatch[0], " ");
  }

  const nextDayMatch = cleaned.match(
    /\bnext\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b/i,
  );
  if (nextDayMatch) {
    const dayName = nextDayMatch[1].toLowerCase();
    const targetIndex = WEEKDAY_NAMES.indexOf(
      dayName as (typeof WEEKDAY_NAMES)[number],
    );
    if (targetIndex >= 0) {
      const todayIndex = now.getDay();
      const daysUntilNext = (targetIndex - todayIndex + 7) % 7 || 7;
      result.dueDate = addDays(now, daysUntilNext);
    }
    cleaned = cleaned.replace(nextDayMatch[0], " ");
  }

  result.cleanedText = cleaned.replace(/\s+/g, " ").trim();
  return result;
}
