import { defineComponent } from "@openuidev/react-lang";
import React from "react";
import {
  Label,
  PolarAngleAxis,
  PolarGrid,
  PolarRadiusAxis,
  RadialBar,
  RadialBarChart,
} from "recharts";
import type { z } from "zod";
import { type ChartConfig, ChartContainer } from "@/components/ui/chart";
import { SquareChart, ToolCard } from "../primitives";
import { gaugeChartSchema } from "../promptSpecs";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const CHART_COLORS = ["#00bbff", "#34d399", "#60a5fa", "#f472b6", "#fb923c"];

// ---------------------------------------------------------------------------
// Views
// ---------------------------------------------------------------------------

const GAUGE_SCALE: Record<string, number> = { sm: 0.8, md: 1, lg: 1.25 };

export function GaugeChartView(props: z.infer<typeof gaugeChartSchema>) {
  const min = props.min ?? 0;
  const max = props.max ?? 100;
  const pct = Math.min(
    100,
    Math.max(0, ((props.value - min) / (max - min)) * 100),
  );
  const warning = props.thresholds?.warning ?? 60;
  const danger = props.thresholds?.danger ?? 80;
  const color =
    pct >= danger ? "#f87171" : pct >= warning ? "#fbbf24" : "#34d399";

  const variant = props.variant ?? "gauge";
  const scale = GAUGE_SCALE[props.size ?? "md"];
  const wrap = (node: React.ReactNode) =>
    scale === 1 ? (
      node
    ) : (
      <div
        style={{ transform: `scale(${scale})`, transformOrigin: "top left" }}
      >
        {node}
      </div>
    );

  if (variant === "text") {
    const textChartConfig: ChartConfig = {
      value: { label: props.title ?? "Value", color },
    };
    const textData = [{ name: "value", value: pct, fill: color }];
    return wrap(
      <ToolCard size="standard" className="p-2 text-center">
        <ChartContainer config={textChartConfig} className="mx-auto">
          <RadialBarChart
            data={textData}
            startAngle={0}
            endAngle={250}
            outerRadius={90}
            innerRadius={70}
            className="mx-auto h-[160px] w-[160px]"
          >
            <PolarGrid
              gridType="circle"
              radialLines={false}
              stroke="none"
              className="first:fill-muted last:fill-background"
              polarRadius={[90, 70]}
            />
            <RadialBar dataKey="value" background cornerRadius={10} />
            <PolarRadiusAxis tick={false} tickLine={false} axisLine={false}>
              <Label
                content={({ viewBox }) => {
                  if (viewBox && "cx" in viewBox && "cy" in viewBox) {
                    return (
                      <text
                        x={viewBox.cx}
                        y={viewBox.cy}
                        textAnchor="middle"
                        dominantBaseline="middle"
                      >
                        <tspan
                          x={viewBox.cx}
                          y={viewBox.cy}
                          fontSize={28}
                          fontWeight="bold"
                          fill={color}
                        >
                          {props.value}
                          {props.unit ?? ""}
                        </tspan>
                        {props.title && (
                          <tspan
                            x={viewBox.cx}
                            y={(viewBox.cy ?? 0) + 22}
                            fontSize={12}
                            fill="#71717a"
                          >
                            {props.title}
                          </tspan>
                        )}
                      </text>
                    );
                  }
                  return null;
                }}
              />
            </PolarRadiusAxis>
          </RadialBarChart>
        </ChartContainer>
      </ToolCard>,
    );
  }

  if (variant === "stacked") {
    const total = props.value + (props.secondValue ?? 0);
    const stackData = [
      { primary: props.value, secondary: props.secondValue ?? 0 },
    ];
    const stackChartConfig: ChartConfig = {
      primary: { label: props.title ?? "Primary", color },
      secondary: {
        label: props.secondLabel ?? "Secondary",
        color: CHART_COLORS[1],
      },
    };
    return wrap(
      <ToolCard size="standard" className="p-2 text-center">
        <ChartContainer config={stackChartConfig} className="mx-auto">
          <RadialBarChart
            data={stackData}
            endAngle={180}
            innerRadius={80}
            outerRadius={110}
            className="mx-auto h-[140px] w-[200px]"
          >
            <RadialBar
              dataKey="secondary"
              fill={CHART_COLORS[1]}
              stackId="a"
              cornerRadius={5}
              className="stroke-transparent stroke-2"
            />
            <RadialBar
              dataKey="primary"
              fill={color}
              stackId="a"
              cornerRadius={5}
              className="stroke-transparent stroke-2"
            />
            <PolarRadiusAxis tick={false} tickLine={false} axisLine={false}>
              <Label
                content={({ viewBox }) => {
                  if (viewBox && "cx" in viewBox && "cy" in viewBox) {
                    return (
                      <text x={viewBox.cx} y={viewBox.cy} textAnchor="middle">
                        <tspan
                          x={viewBox.cx}
                          y={(viewBox.cy ?? 0) - 12}
                          fontSize={22}
                          fontWeight="bold"
                          fill="#e4e4e7"
                        >
                          {total.toLocaleString()}
                        </tspan>
                        <tspan
                          x={viewBox.cx}
                          y={(viewBox.cy ?? 0) + 8}
                          fontSize={12}
                          fill="#71717a"
                        >
                          {props.title ?? "Total"}
                        </tspan>
                      </text>
                    );
                  }
                  return null;
                }}
              />
            </PolarRadiusAxis>
          </RadialBarChart>
        </ChartContainer>
      </ToolCard>,
    );
  }

  // Default: "gauge" variant — single-arc radial chart
  // RadialBar's built-in `background` prop renders the full track, then the
  // filled portion is drawn on top at length proportional to pct.
  const gaugeConfig: ChartConfig = {
    value: { label: props.title ?? "Value", color },
  };
  const gaugeData = [{ name: "value", value: pct, fill: color }];

  return wrap(
    <ToolCard size="full" className="p-3 text-center w-[200px] rounded-3xl">
      <SquareChart config={gaugeConfig}>
        <RadialBarChart
          data={gaugeData}
          startAngle={90}
          endAngle={-270}
          outerRadius="100%"
          innerRadius="80%"
          barSize={14}
        >
          <PolarAngleAxis
            type="number"
            domain={[0, 100]}
            tick={false}
            axisLine={false}
          />
          <RadialBar
            dataKey="value"
            cornerRadius={10}
            background={{ fill: "#3f3f46" }}
          />
          <PolarRadiusAxis tick={false} tickLine={false} axisLine={false}>
            <Label
              content={({ viewBox }) => {
                if (viewBox && "cx" in viewBox && "cy" in viewBox) {
                  return (
                    <text
                      x={viewBox.cx}
                      y={viewBox.cy}
                      textAnchor="middle"
                      dominantBaseline="middle"
                    >
                      <tspan
                        x={viewBox.cx}
                        y={viewBox.cy}
                        fontSize={28}
                        fontWeight="bold"
                        fill={color}
                      >
                        {props.value}
                        {props.unit ?? ""}
                      </tspan>
                      {props.title && (
                        <tspan
                          x={viewBox.cx}
                          y={(viewBox.cy ?? 0) + 22}
                          fontSize={12}
                          fill="#71717a"
                        >
                          {props.title}
                        </tspan>
                      )}
                    </text>
                  );
                }
                return null;
              }}
            />
          </PolarRadiusAxis>
        </RadialBarChart>
      </SquareChart>
    </ToolCard>,
  );
}

// ---------------------------------------------------------------------------
// Component definitions
// ---------------------------------------------------------------------------

export const gaugeChartDef = defineComponent({
  name: "GaugeChart",
  description: "Radial gauge for a value with min/max bounds.",
  props: gaugeChartSchema,
  component: ({ props }) => React.createElement(GaugeChartView, props),
});
