import { formatToolName } from "@/features/chat/utils/chatUtils";

/** `Airtable` and `Google Drive` both reduce to the token their tool names start with. */
function nameToken(name: string): string {
  return name.toLowerCase().replace(/[^a-z0-9]/g, "");
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** Words that cannot be the noun a product name modifies, so removing the name would leave a dangling phrase. */
const FUNCTION_WORDS =
  "a|an|the|and|or|but|for|to|in|on|from|with|by|at|of|as|using|via|within|into|about|when|where|which|that|is|are|was|were|be|been|will|would|can|could|should|must|may|might";
const FUNCTION_WORD = new RegExp(`^(?:${FUNCTION_WORDS})$`, "i");

/** `an organization` but `a user`: the u in user is pronounced "yoo". */
function indefiniteArticle(word: string): "a" | "an" {
  if (/^us/i.test(word)) return "a";
  if (/^eu/i.test(word)) return "a";
  return /^[aeiou]/i.test(word) ? "an" : "a";
}

/**
 * Provider tool names are scoped to their product (`AIRTABLE_CREATE_RECORD`).
 * On that product's own page the scope repeats the H1, so the label is just the
 * action (`Create Record`). Names without the prefix, or a name that is only the
 * prefix, are left as they arrived.
 */
export function displayToolName(
  toolName: string,
  integrationName: string,
): string {
  const prefix = nameToken(integrationName);
  const words = toolName.split("_").filter(Boolean);
  let consumed = "";
  let end = 0;
  while (end < words.length) {
    const next = consumed + words[end].toLowerCase();
    if (!prefix.startsWith(next)) break;
    consumed = next;
    end += 1;
    if (consumed === prefix) break;
  }
  if (consumed !== prefix || end === words.length) {
    return formatToolName(toolName);
  }
  return formatToolName(words.slice(end).join("_"));
}

/**
 * Tool descriptions are written to stand alone, so they repeat the product name
 * the page already carries. Removing it only where it modifies a following
 * common noun keeps proper names (`GitHub Actions`, `Notion API`) intact and
 * leaves the sentence readable. Standalone mentions are kept: they are facts,
 * not template repetition.
 */
export function displayToolDescription(
  description: string,
  integrationName: string,
): string {
  if (!description) return description;
  const name = escapeRegExp(integrationName);
  const startsWithName = new RegExp(`^\\s*${name}\\b`, "i").test(description);

  const cleaned = description
    .replace(new RegExp(`\\bthe\\s+${name}\\s+API\\b`, "gi"), "the API")
    .replace(new RegExp(`\\b${name}\\s+API\\b`, "gi"), "the API")
    .replace(new RegExp(`\\b${name}'s\\b`, "gi"), "its")
    // "update records in Airtable using PUT" reads as "update records using PUT".
    .replace(
      new RegExp(
        `\\b(in|on|from|to|with|by|at|of|via|within|into)\\s+${name}\\s+(?=(?:${FUNCTION_WORDS})\\b)`,
        "gi",
      ),
      "",
    )
    // "an Airtable base" keeps a valid article after the name disappears.
    // Compound product names (GitHub Actions, Slack Enterprise) keep the name.
    .replace(
      new RegExp(
        `\\b(a|an)\\s+${name}\\s+(?!(?:Actions|Pages|Codespaces?|Enterprise|Business|Connect|RTM)\\b)([A-Za-z]+)`,
        "gi",
      ),
      (_match, _article: string, next: string) =>
        `${indefiniteArticle(next)} ${next}`,
    )
    // Only the attributive use: a lowercase word follows the name. A capitalised
    // continuation is part of a product name and stays.
    .replace(
      new RegExp(`\\b${name}\\b\\s+`, "gi"),
      (match, offset: number, full: string) => {
        const nextWord = full
          .slice(offset + match.length)
          .match(/^[A-Za-z]+/)?.[0];
        return nextWord &&
          /^[a-z]/.test(nextWord) &&
          !FUNCTION_WORD.test(nextWord)
          ? ""
          : match;
      },
    )
    .replace(/\s+/g, " ")
    .replace(/\s+([,.;:!?])/g, "$1")
    .trim();

  if (!startsWithName || !cleaned) return cleaned;
  return cleaned.charAt(0).toUpperCase() + cleaned.slice(1);
}
