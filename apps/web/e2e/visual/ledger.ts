import { execFileSync } from "node:child_process";
import { writeFileSync } from "node:fs";
import { join } from "node:path";

/**
 * Mechanical ledger of every styling transformation a diff makes: per hunk,
 * class tokens and HeroUI style props removed vs added, paired by utility
 * family ("rounded-2xl → rounded-3xl", "rounded-xl → radius=lg").
 * Usage: node e2e/visual/ledger.ts <base-ref> <out-dir>
 */

interface Hunk {
  file: string;
  line: number;
  removed: string[];
  added: string[];
}

interface Transform {
  count: number;
  files: Set<string>;
}

const byText = (a: string, b: string) => a.localeCompare(b);

const COLOR =
  "(?:zinc|slate|gray|neutral|stone|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose|primary)";
// Tailwind utility families only, so prose like "self-hosted" inside a string never counts.
const UTILITY_FAMILIES = [
  "(?:bg|text|rounded|border|divide|ring|outline|shadow|fill|stroke|decoration|accent|caret|placeholder)(?:-.+)?",
  "(?:p|m)[xytrbl]?-.+",
  "(?:w|h|size|min-w|min-h|max-w|max-h|gap|gap-x|gap-y|space-x|space-y|inset|top|left|right|bottom|z|opacity|leading|tracking|font|duration|delay|ease|animate|blur|backdrop-blur|translate-x|translate-y|scale|rotate|aspect|line-clamp|basis|order|col-span|row-span|grid-cols|grid-rows)-.+",
  "(?:items|justify|content|place-items|place-content)-(?:start|end|center|between|around|evenly|stretch|baseline|normal)",
  "self-(?:auto|start|end|center|stretch|baseline)",
  `(?:from|via|to)-(?:transparent|black|white|current|${COLOR}(?:-.+)?)`,
  "(?:flex|grid|overflow|overflow-x|overflow-y|whitespace|break|cursor|pointer-events|select|object|origin|transition)(?:-.+)?",
  "(?:truncate|underline|uppercase|lowercase|capitalize|italic|hidden|block|inline|inline-flex|inline-block|contents|relative|absolute|fixed|sticky|grow|shrink)",
];
const UTILITY = new RegExp(
  `^(?:[a-z0-9[\\]&=_-]+:)*!?-?(?:${UTILITY_FAMILIES.join("|")})!?$`,
);
const STYLE_PROP = /\b(radius|variant|color|size|shadow)="([\w-]+)"/g;
const STRING_LITERAL = /"([^"]*)"|'([^']*)'|`([^`]*)`/g;
const TEXT_SIZE = /^text-(xs|sm|base|lg|[2-9]?xl|\[\d+(\.\d+)?(px|rem)\])$/;
const TOP_PER_FAMILY = 12;

function tokensOf(line: string): string[] {
  const tokens: string[] = [];
  for (const prop of line.matchAll(STYLE_PROP))
    tokens.push(`${prop[1]}=${prop[2]}`);
  const withoutProps = line.replace(STYLE_PROP, "");
  for (const literal of withoutProps.matchAll(STRING_LITERAL)) {
    const body = literal[1] ?? literal[2] ?? literal[3] ?? "";
    for (const word of body.split(/\s+/)) {
      if (UTILITY.test(word)) tokens.push(word);
    }
  }
  return tokens;
}

/** The utility family a token belongs to, so a swap is paired with its counterpart. */
function familyOf(token: string): string {
  if (/^(radius|variant|color|size|shadow)=/.test(token)) return "prop";
  const base = token
    .replace(/^.*:/, "")
    .replace(/^!|!$/g, "")
    .replace(/^-/, "");
  if (base.startsWith("text-"))
    return TEXT_SIZE.test(base) ? "text-size" : "text-color";
  const prefix = base.split("-")[0];
  if (/^p[xytrbl]?$/.test(prefix)) return "padding";
  if (/^m[xytrbl]?$/.test(prefix)) return "margin";
  if (/^(w|h|size|min|max)$/.test(prefix)) return "sizing";
  return prefix;
}

function subtract(from: string[], minus: string[]): string[] {
  const left = [...minus];
  return from.filter((token) => {
    const at = left.indexOf(token);
    if (at === -1) return true;
    left.splice(at, 1);
    return false;
  });
}

function parseHunks(diff: string): Hunk[] {
  const hunks: Hunk[] = [];
  let file = "";
  let current: Hunk | null = null;
  for (const line of diff.split("\n")) {
    if (line.startsWith("+++ ")) file = line.slice(6);
    else if (line.startsWith("@@")) {
      const start = Number(line.match(/\+(\d+)/)?.[1] ?? 0);
      current = { file, line: start, removed: [], added: [] };
      hunks.push(current);
    } else if (current && line.startsWith("-") && !line.startsWith("---")) {
      current.removed.push(...tokensOf(line));
    } else if (current && line.startsWith("+")) {
      current.added.push(...tokensOf(line));
    }
  }
  return hunks;
}

const SPACING_FAMILIES = new Set(["padding", "margin", "gap", "space"]);
// Classes that cancel a component default; dropping one brings the default back.
const RESET =
  /^(?:border|shadow|outline|ring)-(?:none|0)$|^(?:border|bg)-transparent$/;

const isSpacing = (token: string): boolean =>
  SPACING_FAMILIES.has(familyOf(token));
const isReset = (token: string): boolean =>
  RESET.test(token.replace(/^.*:/, "").replace(/^!|!$/g, ""));

interface Dropped {
  at: string;
  tokens: string[];
}

/**
 * Hunks that drop classes of one kind with none of that kind added back: how a
 * restyle fix silently collapses a layout (a header loses its padding) or
 * revives a default (a removed border-none brings the sidebar's border back).
 */
function dropped(hunks: Hunk[], isKind: (token: string) => boolean): Dropped[] {
  return hunks.flatMap((hunk) => {
    const dropped = subtract(hunk.removed, hunk.added).filter(isKind);
    const restored = subtract(hunk.added, hunk.removed).some(isKind);
    return dropped.length > 0 && !restored
      ? [{ at: `${hunk.file}:${hunk.line}`, tokens: dropped }]
      : [];
  });
}

function record(
  ledger: Map<string, Map<string, Transform>>,
  family: string,
  key: string,
  file: string,
): void {
  const transforms = ledger.get(family) ?? new Map<string, Transform>();
  ledger.set(family, transforms);
  const entry = transforms.get(key) ?? { count: 0, files: new Set<string>() };
  transforms.set(key, entry);
  entry.count += 1;
  entry.files.add(file);
}

function buildLedger(hunks: Hunk[]): Map<string, Map<string, Transform>> {
  const ledger = new Map<string, Map<string, Transform>>();
  for (const hunk of hunks) {
    const removed = subtract(hunk.removed, hunk.added);
    const added = subtract(hunk.added, hunk.removed);
    const byFamily = (tokens: string[]) =>
      Map.groupBy(tokens, familyOf) as Map<string, string[]>;
    const removedFamilies = byFamily(removed);
    const addedFamilies = byFamily(added);
    const orphanRemoved: string[] = [];
    for (const [family, tokens] of removedFamilies) {
      const counterpart = addedFamilies.get(family);
      if (counterpart && family !== "prop") {
        record(
          ledger,
          family,
          `${tokens.sort(byText).join(" ")} → ${counterpart.sort(byText).join(" ")}`,
          hunk.file,
        );
        addedFamilies.delete(family);
      } else orphanRemoved.push(...tokens);
    }
    const props = addedFamilies.get("prop") ?? [];
    addedFamilies.delete("prop");
    if (props.length > 0 && orphanRemoved.length > 0) {
      record(
        ledger,
        "class → prop",
        `${orphanRemoved.sort(byText).join(" ")} → ${props.sort(byText).join(" ")}`,
        hunk.file,
      );
    } else {
      for (const token of orphanRemoved)
        record(ledger, familyOf(token), `${token} → (removed)`, hunk.file);
      for (const token of props)
        record(ledger, "prop", `(added) → ${token}`, hunk.file);
    }
    for (const [family, tokens] of addedFamilies) {
      for (const token of tokens)
        record(ledger, family, `(added) → ${token}`, hunk.file);
    }
  }
  return ledger;
}

function render(
  ledger: Map<string, Map<string, Transform>>,
  baseRef: string,
  fileCount: number,
  spacing: Dropped[],
  resets: Dropped[],
): string {
  const families = [...ledger].sort(([, a], [, b]) => sum(b) - sum(a));
  const lines = [
    `# Class-change ledger vs ${baseRef}`,
    "",
    `${fileCount} styled files changed. Each row is one before → after swap inside a diff hunk; "files" is how many files make it.`,
    "",
    `## Spacing dropped with no replacement (${spacing.length}) — check each`,
    "",
    ...spacing.map(
      ({ at, tokens }) => `- \`${at}\` lost \`${tokens.join(" ")}\``,
    ),
    "",
    `## Resets dropped, a component default may reappear (${resets.length}) — check each`,
    "",
    ...resets.map(
      ({ at, tokens }) => `- \`${at}\` lost \`${tokens.join(" ")}\``,
    ),
    "",
    "## Families",
    "",
    "| Family | Swaps | Distinct transforms |",
    "| --- | --- | --- |",
    ...families.map(
      ([family, transforms]) =>
        `| ${family} | ${sum(transforms)} | ${transforms.size} |`,
    ),
    "",
  ];
  for (const [family, transforms] of families) {
    const top = [...transforms]
      .sort(([, a], [, b]) => b.count - a.count)
      .slice(0, TOP_PER_FAMILY);
    lines.push(
      `## ${family}`,
      "",
      "| Before → after | Swaps | Files |",
      "| --- | --- | --- |",
    );
    for (const [key, entry] of top)
      lines.push(`| \`${key}\` | ${entry.count} | ${entry.files.size} |`);
    if (transforms.size > TOP_PER_FAMILY)
      lines.push(`| … ${transforms.size - TOP_PER_FAMILY} more | | |`);
    lines.push("");
  }
  return lines.join("\n");
}

function sum(transforms: Map<string, Transform>): number {
  return [...transforms.values()].reduce(
    (total, entry) => total + entry.count,
    0,
  );
}

const [baseRef, outDir] = process.argv.slice(2);
if (!baseRef || !outDir)
  throw new Error("usage: ledger.ts <base-ref> <out-dir>");
const mergeBase = execFileSync("git", ["merge-base", baseRef, "HEAD"], {
  encoding: "utf8",
}).trim();
// Against the working tree, so uncommitted styling shows up exactly like the screenshots do.
const diff = execFileSync(
  "git",
  ["diff", "-U0", "--no-color", mergeBase, "--", "src/**/*.tsx", "src/**/*.ts"],
  { encoding: "utf8", maxBuffer: 256 * 1024 * 1024 },
);
const hunks = parseHunks(diff);
const ledger = buildLedger(hunks);
const styledFiles = new Set(
  hunks.filter((h) => h.removed.length + h.added.length > 0).map((h) => h.file),
);
writeFileSync(
  join(outDir, "ledger.md"),
  render(
    ledger,
    baseRef,
    styledFiles.size,
    dropped(hunks, isSpacing),
    dropped(hunks, isReset),
  ),
);
console.info(
  `ledger: ${styledFiles.size} styled files, ${ledger.size} families → ${join(outDir, "ledger.md")}`,
);
