import { createLibrary, defineComponent } from "@openuidev/react-lang";
import React from "react";
import { View } from "react-native";
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
// Stack — internal vertical layout wrapper
// ---------------------------------------------------------------------------

const stackSchema = z.object({
  items: z.array(z.unknown()),
});

const rowSchema = z.object({
  items: z.array(z.unknown()),
});

const stackDef = defineComponent({
  name: "Stack",
  description: "Vertical stack of multiple components.",
  props: stackSchema,
  component: ({ props, renderNode }) => (
    <View style={{ flexDirection: "column", gap: 12 }}>
      {(props.items as unknown[]).map((item, i) => (
        // biome-ignore lint/suspicious/noArrayIndexKey: generic opaque items
        <React.Fragment key={i}>{renderNode(item)}</React.Fragment>
      ))}
    </View>
  ),
});

const rowDef = defineComponent({
  name: "Row",
  description: "Horizontal row of equal-width components.",
  props: rowSchema,
  component: ({ props, renderNode }) => (
    <View style={{ flexDirection: "row", gap: 12, alignItems: "stretch" }}>
      {(props.items as unknown[]).map((item, i) => (
        <View
          // biome-ignore lint/suspicious/noArrayIndexKey: generic opaque items
          key={i}
          style={{ flex: 1, minWidth: 0 }}
        >
          {renderNode(item)}
        </View>
      ))}
    </View>
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
    },
    {
      name: "Timeline & Notifications",
      components: ["Timeline", "AlertBanner", "Steps"],
    },
    {
      name: "Code",
      components: ["CodeDiff"],
    },
    {
      name: "Documents",
      components: ["TextDocument"],
    },
  ],
});
