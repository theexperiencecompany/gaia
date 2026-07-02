import { ArrowUpRight01Icon } from "@icons";
import type { ReactNode } from "react";
import type { CommandAction, CommandGroup, CommandItem } from "./types";

// View stack: root → category (one entity's list) → item (its actions).
export type View =
  | { level: "category"; groupId: string }
  | { level: "item"; item: CommandItem };

export type Row =
  | { kind: "category"; id: string; group: CommandGroup }
  | { kind: "item"; id: string; item: CommandItem; canDrill: boolean }
  | { kind: "action"; id: string; action: CommandAction }
  | { kind: "nav"; id: string; label: string; icon: ReactNode; path: string }
  | { kind: "ask"; id: string; query: string }
  | { kind: "back"; id: string };

interface Section {
  id: string;
  heading?: string;
  rows: Row[];
}

/** Rows that never get a number badge (navigation / special affordances). */
export const isNumbered = (row: Row) =>
  row.kind !== "nav" && row.kind !== "back" && row.kind !== "ask";

/** Relevance score for ranking search results (0 = no match). */
function scoreText(q: string, text: string): number {
  if (!text) return 0;
  const t = text.toLowerCase();
  if (t === q) return 100;
  if (t.startsWith(q)) return 80;
  if (t.includes(` ${q}`)) return 60;
  if (t.includes(q)) return 40;
  let i = 0;
  for (const char of t) {
    if (char === q[i]) i++;
    if (i === q.length) return 20;
  }
  return 0;
}

const itemScore = (q: string, item: CommandItem) =>
  scoreText(q, item.title) * 2 +
  scoreText(q, item.subtitle ?? "") +
  scoreText(q, item.keywords ?? "");

const BACK_ROW: Row = { kind: "back", id: "back" };

function matches(query: string, text: string): boolean {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  const haystack = text.toLowerCase();
  if (haystack.includes(q)) return true;
  let i = 0;
  for (const char of haystack) {
    if (char === q[i]) i++;
    if (i === q.length) return true;
  }
  return false;
}

const itemText = (item: CommandItem) =>
  `${item.title} ${item.subtitle ?? ""} ${item.keywords ?? ""}`;

const toItemRow = (item: CommandItem): Row => ({
  kind: "item",
  id: item.id,
  item,
  canDrill: item.actions.length > 0,
});

/** Server results can repeat ids; keep first occurrence so row keys stay unique. */
function dedupeById(items: CommandItem[]): CommandItem[] {
  const seen = new Set<string>();
  return items.filter((item) => {
    if (seen.has(item.id)) return false;
    seen.add(item.id);
    return true;
  });
}

interface SectionParams {
  view: View | undefined;
  query: string;
  groups: CommandGroup[];
  recent: CommandItem[];
  context: { heading: string; item: CommandItem } | null;
  searchChats: CommandItem[];
  searchMessages: CommandItem[];
}

function itemActionSections(item: CommandItem, query: string): Section[] {
  const rows: Row[] = [BACK_ROW];
  for (const a of item.actions) {
    if (matches(query, a.label))
      rows.push({ kind: "action", id: `act:${a.id}`, action: a });
  }
  return [{ id: "actions", rows }];
}

function categorySections(group: CommandGroup, query: string): Section[] {
  const rows: Row[] = [BACK_ROW];
  if (group.path && matches(query, `go to ${group.heading}`)) {
    rows.push({
      kind: "nav",
      id: `goto:${group.id}`,
      label: `Go to ${group.heading}`,
      icon: <ArrowUpRight01Icon width={18} height={18} />,
      path: group.path,
    });
  }
  for (const item of group.items) {
    if (matches(query, itemText(item))) rows.push(toItemRow(item));
  }
  return [{ id: group.id, rows }];
}

/** A result section plus a score used to rank it against the others. */
interface ScoredSection {
  section: Section;
  score: number;
}

function scoredSection(
  id: string,
  heading: string,
  items: CommandItem[],
  q: string,
  minScore = 0,
): ScoredSection | null {
  const ranked = items
    .map((item) => ({ item, score: Math.max(itemScore(q, item), minScore) }))
    .filter((r) => r.score > 0)
    .sort((a, b) => b.score - a.score);
  if (!ranked.length) return null;
  return {
    section: { id, heading, rows: ranked.map((r) => toItemRow(r.item)) },
    score: ranked[0].score,
  };
}

function searchSections(params: SectionParams): Section[] {
  const { groups, query, searchChats, searchMessages } = params;
  const q = query.trim().toLowerCase();
  const sections: Section[] = [];

  // "Jump to" — categories whose name matches (e.g. "workflows" → Workflows).
  const jump = groups
    .filter((g) => g.kind === "entity" && scoreText(q, g.heading) > 0)
    .sort((a, b) => scoreText(q, b.heading) - scoreText(q, a.heading))
    .map<Row>((g) => ({ kind: "category", id: `cat:${g.id}`, group: g }));
  if (jump.length)
    sections.push({ id: "jump", heading: "Jump to", rows: jump });

  // Result sections, each scored so the most relevant type floats to the top.
  const results: ScoredSection[] = [];

  const chatGroup = groups.find((g) => g.id === "chats");
  const localChats = chatGroup?.items ?? [];
  const localIds = new Set(localChats.map((i) => i.id));
  const allChats = dedupeById([
    ...localChats.filter((i) => itemScore(q, i) > 0),
    ...searchChats.filter((i) => !localIds.has(i.id)),
  ]);
  // Server hits are relevant even if the local scorer can't see the body.
  const chatSection = scoredSection("chats", "Chats", allChats, q, 30);
  if (chatSection) results.push(chatSection);

  const msgSection = scoredSection(
    "messages",
    "Messages",
    dedupeById(searchMessages),
    q,
    30,
  );
  if (msgSection) results.push(msgSection);

  for (const group of groups) {
    if (group.id === "chats") continue;
    const scored = scoredSection(group.id, group.heading, group.items, q);
    if (scored) results.push(scored);
  }

  results.sort((a, b) => b.score - a.score);
  sections.push(...results.map((r) => r.section));

  // Always offer the AI escape hatch.
  sections.push({ id: "ask", rows: [{ kind: "ask", id: "ask", query }] });
  return sections;
}

function rootSections(params: SectionParams): Section[] {
  const { groups, recent, context } = params;
  const sections: Section[] = [];

  if (context) {
    sections.push({
      id: "context",
      heading: context.heading,
      rows: [toItemRow(context.item)],
    });
  }

  const contextId = context?.item.id;
  const recentRows = recent
    .filter((item) => item.id !== contextId)
    .map(toItemRow);
  if (recentRows.length)
    sections.push({ id: "recent", heading: "Recent", rows: recentRows });

  // Render command groups (kind "actions") as flat sections in order, and fold
  // all entity groups into a single "Browse" section at the first entity slot.
  let browseInserted = false;
  for (const group of groups) {
    if (group.kind === "entity") {
      if (browseInserted) continue;
      browseInserted = true;
      const entities = groups.filter((g) => g.kind === "entity");
      sections.push({
        id: "browse",
        heading: "Browse",
        rows: entities.map((g) => ({
          kind: "category",
          id: `cat:${g.id}`,
          group: g,
        })),
      });
      continue;
    }
    if (group.items.length) {
      sections.push({
        id: group.id,
        heading: group.heading,
        rows: group.items.map(toItemRow),
      });
    }
  }
  return sections;
}

export function buildSections(params: SectionParams): Section[] {
  const { view, query, groups } = params;
  if (view?.level === "item") return itemActionSections(view.item, query);
  if (view?.level === "category") {
    const group = groups.find((g) => g.id === view.groupId);
    return group ? categorySections(group, query) : [];
  }
  if (query.trim()) return searchSections(params);
  return rootSections(params);
}
