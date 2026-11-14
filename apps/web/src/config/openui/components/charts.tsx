import {
  type ComponentRenderProps,
  defineComponent,
} from "@openuidev/react-lang";
import {
  AreaChartCondensed,
  BarChartCondensed,
  HorizontalBarChart,
  LineChartCondensed,
  PieChart,
  RadarChart,
  RadialChart,
  ScatterChart,
  SingleStackedBar,
} from "@openuidev/react-ui/Charts";
import { openuiLibrary } from "@openuidev/react-ui/genui-lib";
import type { ReactNode } from "react";
import { orderedPalette } from "../palette";
import { CHART_PALETTE, PIE_PALETTE } from "../theme";

/**
 * react-ui's chart components, registered under genui-lib's names and schemas.
 *
 * genui-lib bundles its own copy of react-ui's theme context, so its charts never see the
 * app's ThemeProvider: they drew react-ui's light palette and light surface tokens in the dark
 * app. These defs keep genui-lib's prompt contract (same name, props and description) and
 * render the `Charts` components, which read the app theme, with the GAIA palette in order.
 */

type Props = Record<string, unknown>;
type Point = Record<string, string | number>;

const ui = openuiLibrary.components;

function asArray(value: unknown): unknown[] {
  if (Array.isArray(value)) return value;
  return value == null ? [] : [value];
}

function nodeProps(value: unknown): Props | null {
  if (typeof value !== "object" || value === null) return null;
  const node = value as { type?: unknown; props?: unknown };
  if (node.type === "element") return (node.props as Props | undefined) ?? null;
  return value as Props;
}

/** labels + Series(category, values) nodes, or header labels + row arrays, as chart points. */
function seriesPoints(labels: unknown, series: unknown): Point[] {
  const names = asArray(labels).map(String);
  const rows = asArray(series);
  if (Array.isArray(rows[0])) {
    return rows.map((row) => {
      const cells = row as unknown[];
      const point: Point = { category: String(cells[0] ?? "") };
      names.slice(1).forEach((name, i) => {
        point[name] = Number(cells[i + 1]) || 0;
      });
      return point;
    });
  }
  const seriesProps = rows.map(nodeProps).filter((p): p is Props => !!p);
  return names.map((label, i) => {
    const point: Point = { category: label };
    for (const s of seriesProps) {
      const values = asArray(s.values);
      if (typeof s.category === "string" && i < values.length) {
        point[s.category] = Number(values[i]) || 0;
      }
    }
    return point;
  });
}

function seriesCount(points: Point[]): number {
  return Math.max(1, Object.keys(points[0] ?? {}).length - 1);
}

/** labels + values arrays, or Slice(category, value) nodes, as category/value points. */
function slicePoints(labels: unknown, values: unknown): Point[] {
  const vals = asArray(values);
  if (vals.length) {
    return asArray(labels).map((category, i) => ({
      category: String(category),
      value: Number(vals[i]) || 0,
    }));
  }
  return asArray(labels)
    .map(nodeProps)
    .filter((p): p is Props => !!p)
    .map((p) => ({
      category: String(p.category),
      value: Number(p.value) || 0,
    }));
}

function text(value: unknown): string | undefined {
  return typeof value === "string" ? value : undefined;
}

function lineVariant(
  value: unknown,
): "linear" | "natural" | "step" | undefined {
  return value === "linear" || value === "natural" || value === "step"
    ? value
    : undefined;
}

function barVariant(value: unknown): "grouped" | "stacked" | undefined {
  return value === "grouped" || value === "stacked" ? value : undefined;
}

interface CartesianView {
  data: Point[];
  props: Props;
  palette: string[];
}

function cartesianDef(name: string, view: (v: CartesianView) => ReactNode) {
  return defineComponent({
    name,
    props: ui[name].props,
    description: ui[name].description,
    component: ({ props }: ComponentRenderProps<Props>) => {
      const data = seriesPoints(props.labels, props.series);
      if (!data.length) return null;
      return view({
        data,
        props,
        palette: orderedPalette(CHART_PALETTE, seriesCount(data)),
      });
    },
  });
}

const radarChartDef = defineComponent({
  name: "RadarChart",
  props: ui.RadarChart.props,
  description: ui.RadarChart.description,
  component: ({ props }: ComponentRenderProps<Props>) => {
    const data = seriesPoints(props.labels, props.series);
    if (!data.length) return null;
    return (
      <RadarChart
        data={data}
        categoryKey="category"
        customPalette={orderedPalette(CHART_PALETTE, seriesCount(data))}
        isAnimationActive={false}
      />
    );
  },
});

/** react-ui's PieChart contract, drawn in the given palette; the artifact library reuses it. */
export function pieChartDef(palette: readonly string[]) {
  return defineComponent({
    name: "PieChart",
    props: ui.PieChart.props,
    description: ui.PieChart.description,
    component: ({ props }: ComponentRenderProps<Props>) => {
      const data = slicePoints(props.labels, props.values);
      if (!data.length) return null;
      return (
        <PieChart
          data={data}
          categoryKey="category"
          dataKey="value"
          variant={props.variant === "donut" ? "donut" : "pie"}
          appearance={
            props.appearance === "semiCircular" ? "semiCircular" : "circular"
          }
          customPalette={orderedPalette(palette, data.length)}
          isAnimationActive={false}
        />
      );
    },
  });
}

const radialChartDef = defineComponent({
  name: "RadialChart",
  props: ui.RadialChart.props,
  description: ui.RadialChart.description,
  component: ({ props }: ComponentRenderProps<Props>) => {
    const data = slicePoints(props.labels, props.values);
    if (!data.length) return null;
    return (
      <RadialChart
        data={data}
        categoryKey="category"
        dataKey="value"
        customPalette={orderedPalette(PIE_PALETTE, data.length)}
        isAnimationActive={false}
      />
    );
  },
});

const singleStackedBarChartDef = defineComponent({
  name: "SingleStackedBarChart",
  props: ui.SingleStackedBarChart.props,
  description: ui.SingleStackedBarChart.description,
  component: ({ props }: ComponentRenderProps<Props>) => {
    const data = slicePoints(props.labels, props.values);
    if (!data.length) return null;
    return (
      <SingleStackedBar
        data={data}
        categoryKey="category"
        dataKey="value"
        customPalette={orderedPalette(PIE_PALETTE, data.length)}
      />
    );
  },
});

const scatterChartDef = defineComponent({
  name: "ScatterChart",
  props: ui.ScatterChart.props,
  description: ui.ScatterChart.description,
  component: ({ props }: ComponentRenderProps<Props>) => {
    const data = asArray(props.datasets)
      .map(nodeProps)
      .filter((p): p is Props => !!p)
      .map((dataset) => ({
        name: String(dataset.name ?? ""),
        data: asArray(dataset.points)
          .map(nodeProps)
          .filter((p): p is Props => !!p)
          .map((pt) => ({
            x: Number(pt.x),
            y: Number(pt.y),
            ...(pt.z == null ? {} : { z: Number(pt.z) }),
          })),
      }));
    if (!data.length) return null;
    return (
      <ScatterChart
        data={data}
        xAxisDataKey="x"
        yAxisDataKey="y"
        xAxisLabel={text(props.xLabel)}
        yAxisLabel={text(props.yLabel)}
        customPalette={orderedPalette(CHART_PALETTE, data.length)}
        isAnimationActive={false}
      />
    );
  },
});

export const chartDefs = [
  cartesianDef("LineChart", ({ data, props, palette }) => (
    <LineChartCondensed
      data={data}
      categoryKey="category"
      variant={lineVariant(props.variant)}
      xAxisLabel={text(props.xLabel)}
      yAxisLabel={text(props.yLabel)}
      customPalette={palette}
      isAnimationActive={false}
    />
  )),
  cartesianDef("AreaChart", ({ data, props, palette }) => (
    <AreaChartCondensed
      data={data}
      categoryKey="category"
      variant={lineVariant(props.variant)}
      xAxisLabel={text(props.xLabel)}
      yAxisLabel={text(props.yLabel)}
      customPalette={palette}
      isAnimationActive={false}
    />
  )),
  cartesianDef("BarChart", ({ data, props, palette }) => (
    <BarChartCondensed
      data={data}
      categoryKey="category"
      variant={barVariant(props.variant)}
      xAxisLabel={text(props.xLabel)}
      yAxisLabel={text(props.yLabel)}
      customPalette={palette}
      isAnimationActive={false}
    />
  )),
  cartesianDef("HorizontalBarChart", ({ data, props, palette }) => (
    <HorizontalBarChart
      data={data}
      categoryKey="category"
      variant={barVariant(props.variant)}
      xAxisLabel={text(props.xLabel)}
      yAxisLabel={text(props.yLabel)}
      customPalette={palette}
      isAnimationActive={false}
    />
  )),
  radarChartDef,
  pieChartDef(PIE_PALETTE),
  radialChartDef,
  singleStackedBarChartDef,
  scatterChartDef,
];
