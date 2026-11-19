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
} from "@gaia/artifacts/specs";
import { defineComponent } from "@openuidev/react-lang";
import { AreaChartCondensed } from "@openuidev/react-ui/Charts/AreaChartCondensed";
import { LineChartCondensed } from "@openuidev/react-ui/Charts/LineChartCondensed";
import type { ReactNode } from "react";
import type { z } from "zod";
import { seriesPoints } from "@/config/openui/components/charts";
import { orderedPalette } from "@/config/openui/palette";
import { CHART_PALETTE } from "@/config/openui/theme";
import { BarsView } from "./BarsView";
import { Figure } from "./ChartFigure";
import { FunnelView } from "./FunnelView";
import { GaugeView } from "./GaugeView";
import { HeatmapView } from "./HeatmapView";

// Views stay file-private: this module's surface is the defs (react-refresh/only-export-components).

type ChartProps = z.infer<ReturnType<typeof chartSchema>>;
type Point = ReturnType<typeof seriesPoints>[number];

function points(props: ChartProps): Point[] {
  return seriesPoints(
    props.labels,
    props.series.map(([category, values]) => ({ category, values })),
  );
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
          orderedPalette(CHART_PALETTE, props.series.length),
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
