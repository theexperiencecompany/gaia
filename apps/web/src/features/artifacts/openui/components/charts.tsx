import { defineComponent } from "@openuidev/react-lang";
import { AreaChartCondensed } from "@openuidev/react-ui/Charts/AreaChartCondensed";
import { LineChartCondensed } from "@openuidev/react-ui/Charts/LineChartCondensed";
import type { ReactNode } from "react";
import type { z } from "zod";
import { orderedPalette } from "@/config/openui/palette";
import { ARTIFACT_PALETTE } from "../constants";
import {
  type ArtifactComponentName,
  areaSchema,
  barsSchema,
  type chartSchema,
  describeArtifactComponent,
  funnelSchema,
  gaugeSchema,
  heatmapSchema,
  lineSchema,
  stackedBarsSchema,
} from "../specs";
import { BarsView } from "./BarsView";
import { Figure } from "./ChartFigure";
import { FunnelView } from "./FunnelView";
import { GaugeView } from "./GaugeView";
import { HeatmapView } from "./HeatmapView";

// Views stay file-private: this module's surface is the defs (react-refresh/only-export-components).

type ChartProps = z.infer<ReturnType<typeof chartSchema>>;
type Point = Record<string, string | number>;

const [_FIRST_COLOUR] = ARTIFACT_PALETTE;

function points(props: ChartProps): Point[] {
  return props.labels.map((label, i) => {
    const point: Point = { category: label };
    for (const [name, values] of props.series) point[name] = values[i] ?? 0;
    return point;
  });
}

function seriesChartDef(
  name: ArtifactComponentName,
  schema: ReturnType<typeof chartSchema>,
  chart: (data: Point[], palette: string[]) => ReactNode,
) {
  return defineComponent({
    name,
    description: describeArtifactComponent(name),
    props: schema,
    component: ({ props }) => (
      <Figure title={props.title} subtitle={props.subtitle}>
        {chart(
          points(props),
          orderedPalette(ARTIFACT_PALETTE, props.series.length),
        )}
      </Figure>
    ),
  });
}

export const lineDef = seriesChartDef("Line", lineSchema, (data, palette) => (
  <LineChartCondensed
    data={data}
    categoryKey="category"
    variant="linear"
    customPalette={palette}
    isAnimationActive={false}
  />
));
export const areaDef = seriesChartDef("Area", areaSchema, (data, palette) => (
  <AreaChartCondensed
    data={data}
    categoryKey="category"
    variant="linear"
    customPalette={palette}
    isAnimationActive={false}
  />
));
export const barsDef = seriesChartDef("Bars", barsSchema, (data, palette) => (
  <BarsView data={data} palette={palette} variant="grouped" />
));
export const stackedBarsDef = seriesChartDef(
  "StackedBars",
  stackedBarsSchema,
  (data, palette) => (
    <BarsView data={data} palette={palette} variant="stacked" />
  ),
);

export const funnelDef = defineComponent({
  name: "Funnel",
  description: describeArtifactComponent("Funnel"),
  props: funnelSchema,
  component: ({ props }) => <FunnelView {...props} />,
});

export const gaugeDef = defineComponent({
  name: "Gauge",
  description: describeArtifactComponent("Gauge"),
  props: gaugeSchema,
  component: ({ props }) => <GaugeView {...props} />,
});

export const heatmapDef = defineComponent({
  name: "Heatmap",
  description: describeArtifactComponent("Heatmap"),
  props: heatmapSchema,
  component: ({ props }) => <HeatmapView {...props} />,
});
