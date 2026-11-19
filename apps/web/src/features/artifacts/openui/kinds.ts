/**
 * What each artifact kind's prompt teaches and how statements are named. Read by the prompt
 * generator and the server-side validator only, so it stays out of the browser chunk.
 */
import type { ArtifactKind } from "@gaia/shared/api/generated";
import {
  ARTIFACT_COMPONENT_SPECS,
  REACT_UI_ARTIFACT_COMPONENTS,
} from "./specs";

export const ARTIFACT_KINDS = [
  "dashboard",
  "report",
  "plan",
  "comparison",
  "memo",
  "document",
] as const satisfies readonly ArtifactKind[];
export type { ArtifactKind };

/** The components each kind's prompt teaches, besides the Artifact root. */
export const KIND_COMPONENTS: Record<ArtifactKind, readonly string[]> = {
  dashboard: [
    "Section",
    "Columns",
    "Paragraph",
    "Callout",
    "Stats",
    "Line",
    "Area",
    "Bars",
    "StackedBars",
    "Funnel",
    "Gauge",
    "Heatmap",
    "DataTable",
    "Kanban",
  ],
  report: [
    "Section",
    "Paragraph",
    "Takeaways",
    "Callout",
    "Quote",
    "Stats",
    "Line",
    "Bars",
    "DataTable",
    "Todo",
    "Sources",
  ],
  plan: [
    "Section",
    "Columns",
    "Paragraph",
    "Takeaways",
    "Callout",
    "Stats",
    "DataTable",
    "Kanban",
    "Todo",
    "Sources",
  ],
  comparison: [
    "Section",
    "Columns",
    "Paragraph",
    "Takeaways",
    "Callout",
    "Stats",
    "Bars",
    "StackedBars",
    "DataTable",
    "Sources",
  ],
  memo: [
    "Section",
    "Paragraph",
    "Takeaways",
    "Callout",
    "Quote",
    "Stats",
    "Todo",
    "Sources",
  ],
  document: [
    ...ARTIFACT_COMPONENT_SPECS.flatMap((spec) =>
      spec.name === "Artifact" ? [] : [spec.name],
    ),
    ...REACT_UI_ARTIFACT_COMPONENTS,
  ],
};

/**
 * Statement names come from a fixed list (name + a count from 1 per type), so a slot can
 * name its chart without guessing: {funnel1.worstStepLoss}.
 */
export const STATEMENT_NAMES: Record<string, string> = {
  Section: "section",
  Columns: "columns",
  Paragraph: "para",
  Takeaways: "takeaways",
  Callout: "callout",
  Quote: "quote",
  Stats: "stats",
  Line: "line",
  Area: "area",
  Bars: "bars",
  StackedBars: "stacked",
  Funnel: "funnel",
  Gauge: "gauge",
  Heatmap: "heatmap",
  DataTable: "table",
  Kanban: "kanban",
  Todo: "todo",
  Sources: "sources",
  PieChart: "pie",
  CodeBlock: "code",
  HtmlArtifact: "html",
};
