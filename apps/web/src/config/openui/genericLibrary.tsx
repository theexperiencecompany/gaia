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
  statRowDef,
} from "./components/analytics";
import { codeDiffDef } from "./components/code";
import {
  audioPlayerDef,
  calendarMiniDef,
  carouselDef,
  imageBlockDef,
  imageGalleryDef,
  mapBlockDef,
  numberTickerDef,
  treeViewDef,
  videoBlockDef,
} from "./components/content";
import { textDocumentDef } from "./components/document";
import {
  accordionDef,
  actionCardDef,
  avatarListDef,
  comparisonTableDef,
  dataCardDef,
  fileTreeDef,
  kbdBlockDef,
  progressListDef,
  resultListDef,
  selectableListDef,
  statusCardDef,
  tabsBlockDef,
  tagGroupDef,
} from "./components/layout";
import { alertBannerDef, stepsDef, timelineDef } from "./components/timeline";

export {
  AreaChartView,
  BarChartView,
  GaugeChartView,
  LineChartView,
  PieChartView,
  RadarChartView,
  ScatterChartView,
  StatRowView,
} from "./components/analytics";
export { CodeDiffView } from "./components/code";
export {
  AudioPlayerView,
  CalendarMiniView,
  CarouselView,
  ImageBlockView,
  ImageGalleryView,
  MapBlockView,
  NumberTickerView,
  TreeViewView,
  VideoBlockView,
} from "./components/content";
export { TextDocumentView } from "./components/document";
// Re-export all views so the dev preview page can import from one place.
export {
  AccordionView,
  ActionCardView,
  AvatarListView,
  ComparisonTableView,
  DataCardView,
  FileTreeView,
  KbdBlockView,
  ProgressListView,
  ResultListView,
  SelectableListView,
  StatusCardView,
  TabsBlockView,
  TagGroupView,
} from "./components/layout";
export {
  AlertBannerView,
  StepsView,
  TimelineView,
} from "./components/timeline";

// ---------------------------------------------------------------------------
// Stack — internal layout wrapper (not LLM-visible as a standalone component)
// ---------------------------------------------------------------------------

const stackSchema = z.object({
  items: z.array(z.unknown()),
});

const rowSchema = z.object({
  items: z.array(z.unknown()),
});

// ---------------------------------------------------------------------------
// defineComponent calls
// ---------------------------------------------------------------------------

const stackDef = defineComponent({
  name: "Stack",
  description: "Vertical stack of multiple components.",
  props: stackSchema,
  component: ({ props, renderNode }) => (
    <div className="flex flex-col gap-3">
      {(props.items as unknown[]).map((item, i) => (
        // biome-ignore lint/suspicious/noArrayIndexKey: generic opaque items have no stable key
        <React.Fragment key={i}>{renderNode(item)}</React.Fragment>
      ))}
    </div>
  ),
});

const rowDef = defineComponent({
  name: "Row",
  description: "Horizontal row of equal-width components.",
  props: rowSchema,
  component: ({ props, renderNode }) => (
    <div className="flex flex-row gap-3 items-stretch">
      {(props.items as unknown[]).map((item, i) => (
        // biome-ignore lint/suspicious/noArrayIndexKey: generic opaque items have no stable key
        <div key={i} className="flex-1 min-w-0 aspect-video *:h-full">
          {renderNode(item)}
        </div>
      ))}
    </div>
  ),
});

// ---------------------------------------------------------------------------
// Library assembly
// ---------------------------------------------------------------------------

export const genericLibrary = createLibrary({
  components: [
    stackDef,
    rowDef,
    dataCardDef,
    resultListDef,
    comparisonTableDef,
    statusCardDef,
    actionCardDef,
    tagGroupDef,
    fileTreeDef,
    accordionDef,
    tabsBlockDef,
    progressListDef,
    selectableListDef,
    avatarListDef,
    kbdBlockDef,
    statRowDef,
    barChartDef,
    lineChartDef,
    areaChartDef,
    pieChartDef,
    scatterChartDef,
    radarChartDef,
    gaugeChartDef,
    imageBlockDef,
    imageGalleryDef,
    videoBlockDef,
    audioPlayerDef,
    mapBlockDef,
    calendarMiniDef,
    numberTickerDef,
    carouselDef,
    treeViewDef,
    timelineDef,
    alertBannerDef,
    stepsDef,
    codeDiffDef,
    textDocumentDef,
  ],
  componentGroups: [
    {
      name: "Layout & Data",
      components: [
        "DataCard",
        "ResultList",
        "ComparisonTable",
        "StatusCard",
        "ActionCard",
        "TagGroup",
        "FileTree",
        "Accordion",
        "TabsBlock",
        "ProgressList",
        "SelectableList",
        "AvatarList",
        "KbdBlock",
      ],
      notes: ["DataCard for single records", "ResultList for collections"],
    },
    {
      name: "Analytics",
      components: [
        "StatRow",
        "BarChart",
        "LineChart",
        "AreaChart",
        "PieChart",
        "ScatterChart",
        "RadarChart",
        "GaugeChart",
      ],
      notes: [
        "StatRow for single KPI",
        "GaugeChart for value with min/max bounds",
        "RadarChart for multi-axis comparisons",
      ],
    },
    {
      name: "Content",
      components: [
        "ImageBlock",
        "ImageGallery",
        "VideoBlock",
        "AudioPlayer",
        "MapBlock",
        "CalendarMini",
        "NumberTicker",
        "Carousel",
        "TreeView",
      ],
      notes: [
        "VideoBlock auto-embeds YouTube and Vimeo URLs",
        "MapBlock renders OpenStreetMap for any lat/lng",
      ],
    },
    {
      name: "Timeline & Notifications",
      components: ["Timeline", "AlertBanner", "Steps"],
      notes: [
        "Timeline for event sequences",
        "AlertBanner for inline notices",
        "Steps for ordered instructions",
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
