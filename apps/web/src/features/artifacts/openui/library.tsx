import { ARTIFACT_ROOT } from "@gaia/artifacts/specs";
import { createLibrary } from "@openuidev/react-lang";
import { openuiLibrary } from "@openuidev/react-ui/genui-lib";
import { pieChartDef } from "@/config/openui/components/charts";
import { CHART_PALETTE } from "@/config/openui/theme";
import {
  areaDef,
  barsDef,
  funnelDef,
  gaugeDef,
  heatmapDef,
  lineDef,
  stackedBarsDef,
} from "./components/charts";
import { dataTableDef } from "./components/DataTable";
import { kanbanDef, statsDef } from "./components/data";
import { htmlArtifactDef } from "./components/HtmlArtifact";
import {
  artifactDef,
  calloutDef,
  columnsDef,
  paragraphDef,
  quoteDef,
  sectionDef,
  sourcesDef,
  takeawaysDef,
  todoDef,
} from "./components/text";

/**
 * The artifact library: GAIA's artifact components (specs.ts) plus react-ui's PieChart, Slice
 * and CodeBlock. A second createLibrary beside the chat one, rendered by the same Renderer.
 */
export const artifactLibrary = createLibrary({
  root: ARTIFACT_ROOT,
  components: [
    artifactDef,
    sectionDef,
    columnsDef,
    paragraphDef,
    takeawaysDef,
    calloutDef,
    quoteDef,
    statsDef,
    lineDef,
    areaDef,
    barsDef,
    stackedBarsDef,
    funnelDef,
    gaugeDef,
    heatmapDef,
    dataTableDef,
    kanbanDef,
    todoDef,
    sourcesDef,
    htmlArtifactDef,
    pieChartDef(CHART_PALETTE),
    openuiLibrary.components.Slice,
    openuiLibrary.components.CodeBlock,
  ],
});
