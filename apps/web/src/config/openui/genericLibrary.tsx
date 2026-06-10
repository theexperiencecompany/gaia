import { createLibrary, defineComponent } from "@openuidev/react-lang";
import React from "react";
import { z } from "zod";
import {
  areaChartDef,
  barChartDef,
  gaugeChartDef,
  lineChartDef,
  pieChartDef,
  radarChartDef,
  scatterChartDef,
} from "./components/analytics";
import { codeDiffDef } from "./components/code";
import {
  audioPlayerDef,
  carouselDef,
  imageGalleryDef,
  mapBlockDef,
  numberTickerDef,
  videoBlockDef,
} from "./components/content";
import { textDocumentDef } from "./components/document";
import {
  accordionDef,
  copyableContentDef,
  fileTreeDef,
  kbdRowDef,
  tabsBlockDef,
} from "./components/layout";
import {
  avatarDef,
  buttonDef,
  buttonsDef,
  calloutDef,
  cardHeaderDef,
  checkboxDef,
  colDef,
  progressDef,
  radioDef,
  statDef,
  tableDef,
  tagBlockDef,
  tagDef,
  textContentDef,
} from "./components/primitives";
import { stepsDef, timelineDef } from "./components/timeline";

export {
  AreaChartView,
  BarChartView,
  GaugeChartView,
  LineChartView,
  PieChartView,
  RadarChartView,
  ScatterChartView,
} from "./components/analytics";
export { CodeDiffView } from "./components/code";
export {
  AudioPlayerView,
  CarouselView,
  ImageGalleryView,
  MapBlockView,
  NumberTickerView,
  VideoBlockView,
} from "./components/content";
export { TextDocumentView } from "./components/document";
export {
  AccordionView,
  CopyableContentView,
  FileTreeView,
  KbdRowView,
  TabsBlockView,
} from "./components/layout";
export {
  AvatarView,
  ButtonsView,
  ButtonView,
  CalloutView,
  CardHeaderView,
  CheckboxView,
  ProgressView,
  RadioView,
  StatView,
  TableView,
  TagBlockView,
  TagView,
  TextContentView,
} from "./components/primitives";
export { StepsView, TimelineView } from "./components/timeline";

// ---------------------------------------------------------------------------
// Layout primitives
// ---------------------------------------------------------------------------

const stackSchema = z.object({
  items: z.array(z.unknown()),
  direction: z.enum(["row", "column"]).optional(),
  gap: z.enum(["xs", "s", "m", "l", "xl"]).optional(),
  align: z.enum(["start", "center", "end", "stretch"]).optional(),
  justify: z.enum(["start", "center", "end", "between", "around"]).optional(),
  // "wrap" lets items flow onto a new line; "scroll" keeps a single row that
  // overflows horizontally (kanban-style). The two intents are mutually
  // exclusive — combining flex-wrap with overflow-x-auto silently disables
  // the scroll behaviour.
  wrap: z.union([z.boolean(), z.enum(["wrap", "scroll"])]).optional(),
});

const rowSchema = z.object({
  items: z.array(z.unknown()),
});

const cardSchema = z.object({
  items: z.array(z.unknown()),
  variant: z.enum(["card", "sunk", "clear"]).optional(),
  direction: z.enum(["column", "row"]).optional(),
  gap: z.enum(["xs", "s", "m", "l"]).optional(),
  align: z.enum(["start", "center", "end", "stretch"]).optional(),
});

const gridSchema = z.object({
  items: z.array(z.unknown()),
  columns: z.number().min(1).max(4).optional(),
});

const columnSchema = z.object({
  items: z.array(z.unknown()),
});

const separatorSchema = z.object({
  label: z.string().optional(),
});

// ---------------------------------------------------------------------------
// defineComponent calls
// ---------------------------------------------------------------------------

const GAP_MAP: Record<string, string> = {
  xs: "gap-1",
  s: "gap-2",
  m: "gap-3",
  l: "gap-5",
  xl: "gap-8",
};
const ALIGN_MAP: Record<string, string> = {
  start: "items-start",
  center: "items-center",
  end: "items-end",
  stretch: "items-stretch",
};
const JUSTIFY_MAP: Record<string, string> = {
  start: "justify-start",
  center: "justify-center",
  end: "justify-end",
  between: "justify-between",
  around: "justify-around",
};

const stackDef = defineComponent({
  name: "Stack",
  description:
    'Flexible container — vertical (default) or horizontal row. Supports gap, align, justify, and wrap ("wrap" flows to a new line, "scroll" / true keeps one row with horizontal scroll for kanban-style overflow).',
  props: stackSchema,
  component: ({ props, renderNode }) => {
    const isRow = props.direction === "row";
    const gap = GAP_MAP[props.gap ?? "m"] ?? "gap-3";
    const align = ALIGN_MAP[props.align ?? ""] ?? "";
    const justify = JUSTIFY_MAP[props.justify ?? ""] ?? "";
    const wrap =
      props.wrap === "wrap"
        ? "flex-wrap"
        : props.wrap === "scroll" || props.wrap === true
          ? "flex-nowrap overflow-x-auto"
          : "";
    const stretch = isRow ? "" : "w-full [&>*]:max-w-full";
    const cls = [
      "flex",
      isRow ? "flex-row" : "flex-col",
      gap,
      align,
      justify,
      wrap,
      stretch,
    ]
      .filter(Boolean)
      .join(" ");
    return (
      <div className={cls}>
        {(props.items as unknown[]).map((item, i) => (
          // biome-ignore lint/suspicious/noArrayIndexKey: generic opaque items have no stable key
          <React.Fragment key={i}>{renderNode(item)}</React.Fragment>
        ))}
      </div>
    );
  },
});

const rowDef = defineComponent({
  name: "Row",
  description: "Horizontal row of equal-width components.",
  props: rowSchema,
  component: ({ props, renderNode }) => (
    <div className="flex flex-wrap gap-3 items-stretch">
      {(props.items as unknown[]).map((item, i) => (
        // biome-ignore lint/suspicious/noArrayIndexKey: generic opaque items have no stable key
        <div key={i} className="flex-1 min-w-[240px]">
          {renderNode(item)}
        </div>
      ))}
    </div>
  ),
});

const CARD_VARIANT_CLS: Record<string, string> = {
  card: "rounded-2xl bg-zinc-800 p-4",
  sunk: "rounded-2xl bg-white/[0.04] p-3",
  clear: "rounded-2xl p-3",
};
const CARD_GAP_MAP: Record<string, string> = {
  xs: "gap-1",
  s: "gap-2",
  m: "gap-3",
  l: "gap-5",
};

const cardDef = defineComponent({
  name: "Card",
  description:
    "Container with variant (card=zinc-800, sunk=subtle inset, clear=transparent). Use CardHeader as a child for title/subtitle. Supports direction, gap, and align.",
  props: cardSchema,
  component: ({ props, renderNode }) => {
    const bg =
      CARD_VARIANT_CLS[props.variant ?? "card"] ?? CARD_VARIANT_CLS.card;
    const isRow = props.direction === "row";
    const gap = CARD_GAP_MAP[props.gap ?? "m"] ?? "gap-3";
    const align = ALIGN_MAP[props.align ?? ""] ?? "";
    const innerCls = ["flex", isRow ? "flex-row" : "flex-col", gap, align]
      .filter(Boolean)
      .join(" ");
    return (
      <div className={`${bg} w-full`}>
        <div className={innerCls}>
          {(props.items as unknown[]).map((item, i) => (
            // biome-ignore lint/suspicious/noArrayIndexKey: generic opaque items have no stable key
            <React.Fragment key={i}>{renderNode(item)}</React.Fragment>
          ))}
        </div>
      </div>
    );
  },
});

const gridDef = defineComponent({
  name: "Grid",
  description: "Responsive grid layout for multiple OpenUI components.",
  props: gridSchema,
  component: ({ props, renderNode }) => {
    const requestedColumns = props.columns ?? 2;
    const columns = Math.max(1, Math.min(4, requestedColumns));
    const gridClass =
      columns === 1
        ? "grid grid-cols-1 gap-3"
        : columns === 2
          ? "grid grid-cols-1 md:grid-cols-2 gap-3"
          : columns === 3
            ? "grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3"
            : "grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-3";

    return (
      <div className={gridClass}>
        {(props.items as unknown[]).map((item, i) => (
          // biome-ignore lint/suspicious/noArrayIndexKey: generic opaque items have no stable key
          <div key={i} className="min-w-0">
            {renderNode(item)}
          </div>
        ))}
      </div>
    );
  },
});

const columnDef = defineComponent({
  name: "Column",
  description: "Vertical column for a stack of components.",
  props: columnSchema,
  component: ({ props, renderNode }) => (
    <div className="flex flex-col gap-3">
      {(props.items as unknown[]).map((item, i) => (
        // biome-ignore lint/suspicious/noArrayIndexKey: generic opaque items have no stable key
        <React.Fragment key={i}>{renderNode(item)}</React.Fragment>
      ))}
    </div>
  ),
});

const separatorDef = defineComponent({
  name: "Separator",
  description: "Visual separator line with optional section label.",
  props: separatorSchema,
  component: ({ props }) => (
    <div className="w-full max-w-4xl">
      {props.label ? (
        <div className="flex items-center gap-3">
          <div className="h-px flex-1 bg-zinc-700" />
          <span className="text-[11px] text-zinc-500 uppercase tracking-wide">
            {props.label}
          </span>
          <div className="h-px flex-1 bg-zinc-700" />
        </div>
      ) : (
        <div className="h-px w-full bg-zinc-700" />
      )}
    </div>
  ),
});

// ---------------------------------------------------------------------------
// Library assembly
// ---------------------------------------------------------------------------

export const genericLibrary = createLibrary({
  components: [
    // Layout containers
    stackDef,
    cardDef,
    gridDef,
    rowDef,
    columnDef,
    separatorDef,
    // Primitives
    textContentDef,
    cardHeaderDef,
    tagDef,
    tagBlockDef,
    calloutDef,
    statDef,
    colDef,
    tableDef,
    buttonDef,
    buttonsDef,
    progressDef,
    avatarDef,
    checkboxDef,
    radioDef,
    // Layout & data components
    copyableContentDef,
    fileTreeDef,
    accordionDef,
    tabsBlockDef,
    kbdRowDef,
    // Analytics
    barChartDef,
    lineChartDef,
    areaChartDef,
    pieChartDef,
    scatterChartDef,
    radarChartDef,
    gaugeChartDef,
    // Content
    imageGalleryDef,
    videoBlockDef,
    audioPlayerDef,
    mapBlockDef,
    numberTickerDef,
    carouselDef,
    // Timeline
    timelineDef,
    stepsDef,
    // Code & docs
    codeDiffDef,
    textDocumentDef,
  ],
  componentGroups: [
    {
      name: "Primitives",
      components: [
        "TextContent",
        "CardHeader",
        "Tag",
        "TagBlock",
        "Callout",
        "Stat",
        "Col",
        "Table",
        "Button",
        "Buttons",
        "Progress",
        "Avatar",
        "Checkbox",
        "Radio",
      ],
      notes: [
        "Col is a data-only child of Table — never render Col standalone",
        "Buttons renders a row of Button children",
        "Use Callout for important notices (not AlertBanner — removed)",
      ],
    },
    {
      name: "Layout",
      components: [
        "Stack",
        "Card",
        "Grid",
        "Row",
        "Column",
        "Separator",
        "CopyableContent",
        "FileTree",
        "Accordion",
        "TabsBlock",
        "KbdRow",
      ],
      notes: [
        "Stack/Card/Grid/Row/Column are composition containers",
        "Card variant: card=zinc-800, sunk=subtle inset, clear=transparent",
        "FileTree variant: file (default) or generic (for non-file hierarchies)",
        "KbdRow is a single shortcut row — compose multiple inside a Card for a reference table",
      ],
    },
    {
      name: "Analytics",
      components: [
        "BarChart",
        "LineChart",
        "AreaChart",
        "PieChart",
        "ScatterChart",
        "RadarChart",
        "GaugeChart",
      ],
      notes: [
        "GaugeChart for value with min/max bounds",
        "RadarChart for multi-axis comparisons",
        "Use Stat primitive for single KPI values instead of StatRow (removed)",
      ],
    },
    {
      name: "Content",
      components: [
        "ImageGallery",
        "VideoBlock",
        "AudioPlayer",
        "MapBlock",
        "NumberTicker",
        "Carousel",
      ],
      notes: [
        "VideoBlock auto-embeds YouTube and Vimeo URLs",
        "MapBlock renders OpenStreetMap for any lat/lng",
      ],
    },
    {
      name: "Timeline",
      components: ["Timeline", "Steps"],
      notes: [
        "Timeline supports actor, links, and action buttons per item",
        "Steps for ordered instructions with complete/active/pending states",
        "AlertBanner removed — use Callout primitive instead",
      ],
    },
    {
      name: "Code",
      components: ["CodeDiff"],
      notes: [
        "CodeDiff for before/after code comparisons with syntax highlighting",
      ],
    },
    {
      name: "Documents",
      components: ["TextDocument"],
      notes: [
        "TextDocument for emails, reports, letters — editable rich text with metadata fields",
      ],
    },
  ],
});
