import {
  WORKFLOW_ICON_CATALOG,
  type WorkflowIconDef,
} from "./workflowIconCatalog.data";

export { WORKFLOW_ICON_CATALOG, type WorkflowIconDef };

/**
 * Vibrant swatches computed in OKLCH (uniform lightness/chroma, evenly spaced
 * hues, gamut-mapped to sRGB) so every color reads equally bright on dark UI.
 */
export const WORKFLOW_ICON_COLORS = [
  "#ff726b", // coral
  "#f68001", // orange
  "#eebe0c", // gold
  "#5fbf49", // green
  "#0ebfa0", // teal
  "#09b7dc", // cyan
  "#72a3fe", // blue
  "#ad8dfe", // violet
  "#e175d9", // magenta
  "#fb6ca0", // pink
] as const;

export const DEFAULT_WORKFLOW_ICON_COLOR = WORKFLOW_ICON_COLORS[6]; // blue

/** Alpha suffix appended to a swatch hex for the icon's tinted background. */
export const WORKFLOW_ICON_BG_ALPHA = "26"; // ~15%

/** Popular automation icons surfaced as suggestions when the picker query is empty. */
export const WORKFLOW_SUGGESTED_ICONS = [
  "AlarmClockIcon", // reminders
  "Mail01Icon", // email automations
  "Calendar01Icon", // scheduling
  "CheckListIcon", // todos / tasks
  "ZapIcon", // generic automation
  "AiMagicIcon", // AI assist
  "NotificationIcon", // nudges / alerts
  "SourceCodeIcon", // dev workflows
  "Dumbbell01Icon", // habits / fitness
  "MoneyBag01Icon", // finance check-ins
  "Book01Icon", // study / reading
  "GlobeIcon", // news / web digests
] as const;

export const WORKFLOW_ICON_MAP: ReadonlyMap<string, WorkflowIconDef> = new Map(
  WORKFLOW_ICON_CATALOG.map((def) => [def.name, def]),
);

/** Normalizes an icon export name for matching: strips a trailing "Icon" and digits, lowercases. */
function normalizeIconName(name: string): string {
  return name.replace(/\d*Icon$/, "").toLowerCase();
}

/** "MoneyBag01Icon" -> ["money", "bag"] — the camelCase words of the icon name. */
function iconNameWords(name: string): string[] {
  return name
    .replace(/\d*Icon$/, "")
    .split(/(?=[A-Z])/)
    .map((word) => word.toLowerCase())
    .filter(Boolean);
}

/** Trim a plural/possessive tail so "reminders" matches "reminder". */
function singularize(term: string): string {
  return term.replace(/'s$|s$/, "");
}

/** Human label for an icon slug: "AlarmClockIcon" -> "Alarm Clock". */
export function workflowIconLabel(name: string): string {
  return name
    .replace(/\d*Icon$/, "")
    .split(/(?=[A-Z])/)
    .join(" ")
    .trim();
}

/** Ranked search: exact/prefix name match > name substring > keyword prefix > keyword substring. Every whitespace-separated query term must match; empty query returns the full catalog. */
export function searchWorkflowIcons(query: string): WorkflowIconDef[] {
  const terms = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
  if (terms.length === 0) {
    return WORKFLOW_ICON_CATALOG;
  }

  const scored: { def: WorkflowIconDef; score: number }[] = [];

  for (const def of WORKFLOW_ICON_CATALOG) {
    const normalizedName = normalizeIconName(def.name);
    const nameWords = iconNameWords(def.name);
    let total = 0;
    let matchesAllTerms = true;

    for (const rawTerm of terms) {
      const variants =
        singularize(rawTerm) === rawTerm
          ? [rawTerm]
          : [rawTerm, singularize(rawTerm)];
      let termScore = 0;
      for (const term of variants) {
        let variantScore = 0;
        if (normalizedName === term || normalizedName.startsWith(term)) {
          variantScore = 5;
        } else if (nameWords.some((word) => word.startsWith(term))) {
          variantScore = 4;
        } else if (normalizedName.includes(term)) {
          variantScore = 3;
        } else if (def.keywords.some((keyword) => keyword.startsWith(term))) {
          variantScore = 2;
        } else if (def.keywords.some((keyword) => keyword.includes(term))) {
          variantScore = 1;
        }
        termScore = Math.max(termScore, variantScore);
      }

      if (termScore === 0) {
        matchesAllTerms = false;
        break;
      }
      total += termScore;
    }

    if (matchesAllTerms) {
      scored.push({ def, score: total });
    }
  }

  scored.sort(
    (a, b) => b.score - a.score || a.def.name.localeCompare(b.def.name),
  );
  return scored.map((entry) => entry.def);
}
