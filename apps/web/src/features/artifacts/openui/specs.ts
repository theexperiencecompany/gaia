/**
 * Node-safe single source for the artifact library: every GAIA artifact component's name,
 * description and props schema, the components each artifact kind may use, and the fixed
 * statement names slots refer to. Imports only zod, so the React library (library.tsx), the
 * prompt generator and the server-side validator all read the same definitions.
 */
import { z } from "zod";

const children = z.array(z.unknown());
const cell = z.union([z.string(), z.number()]).nullable();
const cellRows = z.array(z.array(cell));

export const calloutTone = z.enum(["note", "good", "warn", "risk"]);

export const artifactSchema = z.object({
  title: z.string(),
  subtitle: z.string(),
  details: z.array(z.string()).optional(),
  children,
});
export const sectionSchema = z.object({
  title: z.string(),
  summary: z.string().optional(),
  children,
});
export const columnsSchema = z.object({ children });
export const paragraphSchema = z.object({ text: z.string() });
export const takeawaysSchema = z.object({ items: z.array(z.string()) });
export const calloutSchema = z.object({
  tone: calloutTone,
  title: z.string(),
  text: z.string(),
});
export const quoteSchema = z.object({
  text: z.string(),
  attribution: z.string(),
});
export const statsSchema = z.object({
  items: z.array(z.array(z.string().nullable())),
});
/** One schema per chart component: OpenUI's registry names components by schema object. */
export function chartSchema() {
  return z.object({
    title: z.string(),
    subtitle: z.string(),
    labels: z.array(z.string()),
    series: z.array(z.tuple([z.string(), z.array(z.number())])),
  });
}
export const lineSchema = chartSchema();
export const areaSchema = chartSchema();
export const barsSchema = chartSchema();
export const stackedBarsSchema = chartSchema();
export const funnelSchema = z.object({
  title: z.string(),
  subtitle: z.string().optional(),
  stages: z.array(z.tuple([z.string(), z.number()])),
});
export const gaugeSchema = z.object({
  title: z.string(),
  value: z.number(),
  max: z.number(),
  target: z.number().optional(),
  label: z.string(),
  suffix: z.string().optional(),
});
export const heatmapSchema = z.object({
  title: z.string(),
  subtitle: z.string().optional(),
  rows: z.array(z.string()),
  columns: z.array(z.string()),
  values: z.array(z.array(z.number())),
});
export const dataTableSchema = z.object({
  caption: z.string().nullable().optional(),
  columns: z.array(z.string()),
  numeric: z.array(z.number()).nullable().optional(),
  rows: cellRows,
  details: z
    .union([z.record(z.string(), cellRows), z.array(cellRows.nullable())])
    .nullable()
    .optional(),
  total: z.array(cell).nullable().optional(),
});
export const kanbanSchema = z.object({
  columns: z.array(z.tuple([z.string(), z.array(z.array(z.string()))])),
});
export const todoSchema = z.object({ items: z.array(z.array(z.string())) });
export const sourcesSchema = z.object({
  items: z.array(z.tuple([z.string(), z.string(), z.string().optional()])),
});

export type ArtifactCell = z.infer<typeof cell>;

const CHART_NOTE =
  "title states the message; subtitle: what, unit, period; series: [name, values][].";

export const ARTIFACT_COMPONENT_SPECS = [
  {
    name: "Artifact",
    description:
      "Root. title, subtitle (the answer in one or two sentences), details (up to 3 short facts), children.",
    props: artifactSchema,
  },
  {
    name: "Section",
    description:
      "A titled section. summary: one line saying what it concludes.",
    props: sectionSchema,
  },
  {
    name: "Columns",
    description:
      "Side-by-side layout; each child is one column. Stacks on a phone.",
    props: columnsSchema,
  },
  {
    name: "Paragraph",
    description: "Body text; **bold** allowed.",
    props: paragraphSchema,
  },
  {
    name: "Takeaways",
    description: "The answer first: 1 to 5 short lines.",
    props: takeawaysSchema,
  },
  {
    name: "Callout",
    description:
      'Tinted note. tone: "note"|"good"|"warn"|"risk". title is the point.',
    props: calloutSchema,
  },
  {
    name: "Quote",
    description: "A short quotation with attribution.",
    props: quoteSchema,
  },
  {
    name: "Stats",
    description:
      'Row of stats: items are [label, value, note?, trend? "up"|"down", sentiment? "good"|"bad"].',
    props: statsSchema,
  },
  {
    name: "Line",
    description: `Trend over time. ${CHART_NOTE}`,
    props: lineSchema,
  },
  {
    name: "Area",
    description: `Stacked areas over time, parts of a total. ${CHART_NOTE}`,
    props: areaSchema,
  },
  {
    name: "Bars",
    description: `Compare categories. ${CHART_NOTE}`,
    props: barsSchema,
  },
  {
    name: "StackedBars",
    description: `Parts of a total per category. ${CHART_NOTE}`,
    props: stackedBarsSchema,
  },
  {
    name: "Funnel",
    description:
      "Narrowing stages. title, subtitle, stages: [label, value] pairs, largest first.",
    props: funnelSchema,
  },
  {
    name: "Gauge",
    description: "One value against a range and optional target.",
    props: gaugeSchema,
  },
  {
    name: "Heatmap",
    description:
      "Grid of values. rows, columns: labels; values: rows × columns numbers.",
    props: heatmapSchema,
  },
  {
    name: "DataTable",
    description:
      "Sortable, filterable table. columns: labels; numeric: indexes of numeric columns; rows: arrays of cells; details: optional child rows per row index (drill-down).",
    props: dataTableSchema,
  },
  {
    name: "Kanban",
    description:
      "Board: columns are [title, cards] where a card is [title, meta?, tag?].",
    props: kanbanSchema,
  },
  {
    name: "Todo",
    description:
      "Action rows: items are [verb, rest of the sentence, owner and due?].",
    props: todoSchema,
  },
  {
    name: "Sources",
    description: "Numbered references: [title, publisher, url] triples.",
    props: sourcesSchema,
  },
] as const;

export type ArtifactComponentName =
  (typeof ARTIFACT_COMPONENT_SPECS)[number]["name"];

/** react-ui components the artifact library adopts unchanged. */
export const REACT_UI_ARTIFACT_COMPONENTS = [
  "PieChart",
  "Slice",
  "CodeBlock",
] as const;

export const ARTIFACT_ROOT = "Artifact";

/** A component's prompt description, read by its React def so the two never drift. */
export function describeArtifactComponent(name: ArtifactComponentName): string {
  const spec = ARTIFACT_COMPONENT_SPECS.find((s) => s.name === name);
  if (!spec) throw new Error(`No artifact component spec named ${name}`);
  return spec.description;
}
