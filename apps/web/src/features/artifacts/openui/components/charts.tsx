import { Progress } from "@heroui/progress";
import { defineComponent } from "@openuidev/react-lang";
import { AreaChartCondensed } from "@openuidev/react-ui/Charts/AreaChartCondensed";
import { BarChartCondensed } from "@openuidev/react-ui/Charts/BarChartCondensed";
import { LineChartCondensed } from "@openuidev/react-ui/Charts/LineChartCondensed";
import type { ReactNode } from "react";
import type { z } from "zod";
import { orderedPalette } from "@/config/openui/palette";
import { ARTIFACT_PALETTE } from "../constants";
import { GroundedText } from "../GroundedText";
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

// Views stay file-private: this module's surface is the defs (react-refresh/only-export-components).

type ChartProps = z.infer<ReturnType<typeof chartSchema>>;
type Point = Record<string, string | number>;

const [FIRST_COLOUR] = ARTIFACT_PALETTE;

interface FigureProps {
  title: string;
  subtitle?: string;
  children: ReactNode;
}

function Figure({ title, subtitle, children }: FigureProps) {
  return (
    <figure className="flex min-w-0 flex-col gap-2">
      <figcaption>
        <span className="font-semibold text-foreground">
          <GroundedText text={title} />
        </span>
        {subtitle ? (
          <span className="block text-sm text-default-500">
            <GroundedText text={subtitle} />
          </span>
        ) : null}
      </figcaption>
      {children}
    </figure>
  );
}

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
  <BarChartCondensed
    data={data}
    categoryKey="category"
    variant="grouped"
    customPalette={palette}
    isAnimationActive={false}
  />
));
export const stackedBarsDef = seriesChartDef(
  "StackedBars",
  stackedBarsSchema,
  (data, palette) => (
    <BarChartCondensed
      data={data}
      categoryKey="category"
      variant="stacked"
      customPalette={palette}
      isAnimationActive={false}
    />
  ),
);

function FunnelView(props: z.infer<typeof funnelSchema>) {
  const top = props.stages[0]?.[1] || 1;
  return (
    <Figure title={props.title} subtitle={props.subtitle}>
      {props.stages.map(([label, value], i) => {
        const previous = props.stages[i - 1]?.[1];
        const carried = previous
          ? `${Math.round((value / previous) * 100)}%`
          : null;
        return (
          <div key={label} className="flex flex-col gap-1">
            <div className="flex justify-between gap-3 text-sm">
              <span>{label}</span>
              <span className="flex gap-3 text-default-500 tabular-nums">
                <span>{value.toLocaleString("en")}</span>
                {carried ? (
                  <span className="text-default-400">{carried}</span>
                ) : null}
              </span>
            </div>
            <Progress
              aria-label={label}
              value={(value / top) * 100}
              size="md"
              color="primary"
            />
          </div>
        );
      })}
    </Figure>
  );
}

export const funnelDef = defineComponent({
  name: "Funnel",
  description: describeArtifactComponent("Funnel"),
  props: funnelSchema,
  component: ({ props }) => <FunnelView {...props} />,
});

const GAUGE_ARC = "M20 115 A90 90 0 0 1 200 115";
const GAUGE_LENGTH = Math.PI * 90;

function GaugeView(props: z.infer<typeof gaugeSchema>) {
  const share =
    props.max > 0 ? Math.min(1, Math.max(0, props.value / props.max)) : 0;
  return (
    <figure className="flex flex-col items-center gap-2">
      <figcaption className="self-start font-semibold text-foreground">
        <GroundedText text={props.title} />
      </figcaption>
      <svg
        viewBox="0 0 220 130"
        width="220"
        role="img"
        aria-label={`${props.value}${props.suffix ?? ""}`}
      >
        <path
          d={GAUGE_ARC}
          fill="none"
          className="stroke-default-200"
          strokeWidth="16"
          strokeLinecap="round"
        />
        <path
          d={GAUGE_ARC}
          fill="none"
          stroke={FIRST_COLOUR}
          strokeWidth="16"
          strokeLinecap="round"
          strokeDasharray={`${share * GAUGE_LENGTH} ${GAUGE_LENGTH}`}
        />
        <text
          x="110"
          y="100"
          textAnchor="middle"
          fontSize="30"
          fontWeight="600"
          className="fill-foreground"
        >
          {props.value}
          {props.suffix}
        </text>
      </svg>
      <span className="text-sm text-default-500">
        <GroundedText text={props.label} />
      </span>
    </figure>
  );
}

export const gaugeDef = defineComponent({
  name: "Gauge",
  description: describeArtifactComponent("Gauge"),
  props: gaugeSchema,
  component: ({ props }) => <GaugeView {...props} />,
});

// a cell's tint runs from a faint wash to the full colour; text turns white once it is dark
const HEAT_FLOOR = 0.06;
const HEAT_DARK_TEXT = 0.55;

function HeatmapView(props: z.infer<typeof heatmapSchema>) {
  const hi = Math.max(...props.values.flat()) || 1;
  return (
    <Figure title={props.title} subtitle={props.subtitle}>
      <div className="max-w-full overflow-x-auto">
        <table className="border-separate border-spacing-0.5 text-xs tabular-nums">
          <thead>
            <tr>
              <th className="sticky left-0 z-10 bg-background" />
              {props.columns.map((column) => (
                <th key={column} className="font-normal text-default-500">
                  {column}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {props.rows.map((row, i) => (
              <tr key={row}>
                <th className="sticky left-0 z-10 bg-background pr-2 text-right font-normal">
                  {row}
                </th>
                {(props.values[i] ?? []).map((value, j) => {
                  const share = value / hi;
                  const column = props.columns[j];
                  return (
                    <td
                      key={column}
                      title={`${row} ${column}: ${value}`}
                      className={`h-7 min-w-7 rounded text-center ${share > HEAT_DARK_TEXT ? "text-white" : ""}`}
                      style={{
                        background: `color-mix(in srgb, ${FIRST_COLOUR} ${Math.round((HEAT_FLOOR + share * (1 - HEAT_FLOOR)) * 100)}%, transparent)`,
                      }}
                    >
                      {value}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Figure>
  );
}

export const heatmapDef = defineComponent({
  name: "Heatmap",
  description: describeArtifactComponent("Heatmap"),
  props: heatmapSchema,
  component: ({ props }) => <HeatmapView {...props} />,
});
