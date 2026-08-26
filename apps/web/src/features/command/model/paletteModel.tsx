import { ArrowUpRight01Icon } from "@icons";
import type { ReactNode } from "react";
import type { CommandAction, CommandGroup, CommandItem } from "./types";

// View stack: root → category (one entity's list) → item (its actions).
export type View =
  | { level: "category"; groupId: string }
  | { level: "item"; item: CommandItem };

/** One level of the drill-down stack: what it shows plus the query typed there. */
export interface Level {
  /** Undefined at the root level. */
  view?: View;
  query: string;
}

export type Row =
  | { kind: "category"; id: string; group: CommandGroup }
  | { kind: "item"; id: string; item: CommandItem; canDrill: boolean }
  | { kind: "action"; id: string; action: CommandAction }
  | { kind: "nav"; id: string; label: string; icon: ReactNode; path: string }
  | { kind: "ask"; id: string; query: string }
  | { kind: "back"; id: string }
  | { kind: "loading"; id: string };

interface Section {
  id: string;
  heading?: string;
  rows: Row[];
}

/** Rows that never get a number badge (navigation / special affordances). */
export const isNumbered = (row: Row) =>
  row.kind !== "nav" &&
  row.kind !== "back" &&
  row.kind !== "ask" &&
  row.kind !== "loading";

import { scoreFields } from "./scorer";

/** Relevance of an item for a query across its title/subtitle/keywords. */
const itemScore = (query: string, item: CommandItem) =>
  scoreFields(query, [
    { text: item.title, weight: 2 },
    { text: item.subtitle },
    { text: item.keywords },
  ]);

/** Relevance of any single string for a query (headings, action labels). */
const textScore = (query: string, text: string) =>
  scoreFields(query, [{ text }]);

/** Does a query match at all — used to include/exclude rows while browsing. */
const matchesText = (query: string, text: string): boolean => {
  if (!query.trim()) return true;
  return scoreFields(query, [{ text }]) > 0;
};

const BACK_ROW: Row = { kind: "back", id: "back" };

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
  searchMemories: CommandItem[];
  /** True while a server search/recall request is in flight. */
  searchLoading: boolean;
  /** Extra relevance for items the user has picked before (frecency). */
  boost?: (item: CommandItem) => number;
}

function itemActionSections(item: CommandItem, query: string): Section[] {
  const rows: Row[] = [BACK_ROW];
  for (const a of item.actions) {
    if (matchesText(query, a.label))
      rows.push({ kind: "action", id: `act:${a.id}`, action: a });
  }
  return [{ id: "actions", rows }];
}

function categorySections(group: CommandGroup, query: string): Section[] {
  const rows: Row[] = [BACK_ROW];
  if (group.path && matchesText(query, `go to ${group.heading}`)) {
    rows.push({
      kind: "nav",
      id: `goto:${group.id}`,
      label: `Go to ${group.heading}`,
      icon: <ArrowUpRight01Icon width={18} height={18} />,
      path: group.path,
    });
  }
  for (const link of group.links ?? []) {
    if (matchesText(query, link.label))
      rows.push({
        kind: "nav",
        id: `link:${link.label}`,
        label: link.label,
        icon: <ArrowUpRight01Icon width={18} height={18} />,
        path: link.path,
      });
  }
  for (const item of group.items) {
    // Empty query = browsing: show everything unranked.
    if (!query.trim() || itemScore(query, item) > 0) rows.push(toItemRow(item));
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
  query: string,
  minScore = 0,
  boost?: (item: CommandItem) => number,
): ScoredSection | null {
  const ranked = items
    .map((item) => ({
      item,
      // Frecency boosts near-equal matches but can't push a row past an
      // exact/prefix title match.
      score: Math.min(
        Math.max(itemScore(query, item), minScore) + (boost?.(item) ?? 0),
        200,
      ),
    }))
    .filter((r) => r.score > 0)
    .sort((a, b) => b.score - a.score);
  if (!ranked.length) return null;
  return {
    section: { id, heading, rows: ranked.map((r) => toItemRow(r.item)) },
    score: ranked[0].score,
  };
}

function searchSections(params: SectionParams): Section[] {
  const { groups, query, searchChats, searchMessages, searchMemories, boost } =
    params;
  const sections: Section[] = [];

  // "Jump to" — categories whose name matches (e.g. "workflows" → Workflows).
  const jump = groups
    .filter((g) => g.kind === "entity" && textScore(query, g.heading) > 0)
    .sort((a, b) => textScore(query, b.heading) - textScore(query, a.heading))
    .map<Row>((g) => ({ kind: "category", id: `cat:${g.id}`, group: g }));
  if (jump.length)
    sections.push({ id: "jump", heading: "Jump to", rows: jump });

  // Result sections, each scored so the most relevant type floats to the top.
  const results: ScoredSection[] = [];

  const chatGroup = groups.find((g) => g.id === "chats");
  const localChats = chatGroup?.items ?? [];
  const localIds = new Set(localChats.map((i) => i.id));
  const allChats = dedupeById([
    ...localChats.filter((i) => itemScore(query, i) > 0),
    ...searchChats.filter((i) => !localIds.has(i.id)),
  ]);
  // Server hits are relevant even if the local scorer can't see the body.
  const chatSection = scoredSection(
    "chats",
    "Chats",
    allChats,
    query,
    30,
    boost,
  );
  if (chatSection) results.push(chatSection);

  const msgSection = scoredSection(
    "messages",
    "Messages",
    dedupeById(searchMessages),
    query,
    30,
    boost,
  );
  if (msgSection) results.push(msgSection);

  // Semantic memory recall — merged with the local memories list, server
  // hits deduped against it and floored like the other server facets.
  const memoryGroup = groups.find((g) => g.id === "memories");
  const localMemories = memoryGroup?.items ?? [];
  const localMemoryIds = new Set(localMemories.map((i) => i.id));
  const allMemories = dedupeById([
    ...localMemories.filter((i) => itemScore(query, i) > 0),
    ...searchMemories.filter((i) => !localMemoryIds.has(i.id)),
  ]);
  const memSection = scoredSection(
    "memories",
    "Memories",
    allMemories,
    query,
    30,
    boost,
  );
  if (memSection) results.push(memSection);

  for (const group of groups) {
    // chats + memories have dedicated merged sections above.
    if (group.id === "chats" || group.id === "memories") continue;
    const scored = scoredSection(
      group.id,
      group.heading,
      group.items,
      query,
      0,
      boost,
    );
    if (scored) results.push(scored);
  }

  results.sort((a, b) => b.score - a.score);
  sections.push(...results.map((r) => r.section));

  // First fetch of a query: no server rows to show yet — say so instead of
  // leaving the user wondering whether chats/messages/memories were searched.
  if (params.searchLoading && results.length === 0) {
    sections.push({
      id: "loading",
      heading: "Searching…",
      rows: [{ kind: "loading", id: "search-loading" }],
    });
  }

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
