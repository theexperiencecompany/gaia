import type { GraphThemeColors } from "@supermemory/memory-graph";
import type { MemoryDocType } from "@/features/memory/api/types";

export const MEMORY_PAGE_SIZE = 20;

export const MAX_MEMORY_LENGTH = 500;

export const JOURNAL_RANGE_DAYS = 14;

export const CORE_DOCUMENTS: {
  docType: MemoryDocType;
  fileName: string;
  description: string;
}[] = [
  {
    docType: "user_md",
    fileName: "user.md",
    description: "Who you are — identity, work, places, and routines",
  },
  {
    docType: "memory_md",
    fileName: "memory.md",
    description: "How GAIA assists you — tone, conventions, and preferences",
  },
  {
    docType: "agenda_md",
    fileName: "agenda.md",
    description: "Open loops — active projects, commitments, and deadlines",
  },
  {
    docType: "people_md",
    fileName: "people.md",
    description: "People in your life — names, roles, and key dates",
  },
  {
    docType: "insights_md",
    fileName: "insights.md",
    description: "Patterns GAIA has noticed about your habits",
  },
];

/**
 * GAIA dark theme for @supermemory/memory-graph — zinc scale with the
 * cyan brand accent, matching DESIGN.md tokens.
 */
export const MEMORY_GRAPH_THEME: Partial<GraphThemeColors> = {
  bg: "#111111",
  docFill: "#27272a",
  docStroke: "#3f3f46",
  docInnerFill: "#18181b",
  memFill: "#3f3f46",
  memFillHover: "#52525b",
  memStrokeDefault: "#52525b",
  accent: "#00bbff",
  textPrimary: "#fafafa",
  textSecondary: "#a1a1aa",
  textMuted: "#71717a",
  edgeDerives: "#3f3f46",
  edgeUpdates: "#00bbff",
  edgeExtends: "#71717a",
  memBorderForgotten: "#f87171",
  memBorderExpiring: "#f5a524",
  memBorderRecent: "#00bbff",
  glowColor: "#00bbff",
  iconColor: "#a1a1aa",
  popoverBg: "#18181b",
  popoverBorder: "#27272a",
  popoverTextPrimary: "#fafafa",
  popoverTextSecondary: "#a1a1aa",
  popoverTextMuted: "#71717a",
  controlBg: "#18181b",
  controlBorder: "#27272a",
};
