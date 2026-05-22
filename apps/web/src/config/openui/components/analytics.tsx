import { defineComponent } from "@openuidev/react-lang";
import React from "react";
import {
  Area,
  Bar,
  CartesianGrid,
  Cell,
  Label,
  LabelList,
  Line,
  Pie,
  PolarAngleAxis,
  PolarGrid,
  PolarRadiusAxis,
  Radar,
  RadialBar,
  RadialBarChart,
  AreaChart as RechartsAreaChart,
  BarChart as RechartsBarChart,
  LineChart as RechartsLineChart,
  PieChart as RechartsPieChart,
  RadarChart as RechartsRadarChart,
  ScatterChart as RechartsScatterChart,
  Scatter,
  XAxis,
  YAxis,
} from "recharts";
import { z } from "zod";
import {
  type ChartConfig,
  ChartContainer,
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
  ChartTooltipContent,
} from "@/components/ui/chart";
import { SquareChart, ToolCard } from "../primitives";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const CHART_COLORS = ["#00bbff", "#34d399", "#60a5fa", "#f472b6", "#fb923c"];
const PIE_COLORS = ["#00bbff", "#34d399", "#60a5fa", "#a78bfa", "#f472b6"];

/** Coerce a string | string[] to string[] so charts never break on a bare string. */
function toKeys(v: string | string[]): string[] {
  return Array.isArray(v) ? v : [v];
}

/** Compact number formatter: 1500 → "1.5K", 1200000 → "1.2M" */
function fmtNum(v: number): string {
  if (Math.abs(v) >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`;
  if (Math.abs(v) >= 1_000) return `${(v / 1_000).toFixed(1)}K`;
  return String(v);
}

// ---------------------------------------------------------------------------
// Schemas
// ---------------------------------------------------------------------------

const chartDataSchema = z.array(
  z.record(z.string(), z.union([z.string(), z.number()])),
);

export const barChartSchema = z.object({
  data: chartDataSchema,
  xKey: z.string(),
  yKeys: z.union([z.array(z.string()), z.string()]),
  title: z.string().optional(),
  description: z.string().optional(),
  footer: z.string().optional(),
  colors: z.array(z.string()).optional(),
  variant: z.enum(["default", "stacked", "horizontal", "multiple"]).optional(),
});

export const lineChartSchema = z.object({
  data: chartDataSchema,
  xKey: z.string(),
  yKeys: z.union([z.array(z.string()), z.string()]),
  title: z.string().optional(),
  description: z.string().optional(),
  footer: z.string().optional(),
  colors: z.array(z.string()).optional(),
  showDots: z.boolean().optional(),
  showLabels: z.boolean().optional(),
});

export const areaChartSchema = z.object({
  data: chartDataSchema,
  xKey: z.string(),
  yKeys: z.union([z.array(z.string()), z.string()]),
  title: z.string().optional(),
  description: z.string().optional(),
  footer: z.string().optional(),
  colors: z.array(z.string()).optional(),
});

export const pieChartSchema = z.object({
  data: chartDataSchema,
  nameKey: z.string(),
  valueKey: z.string(),
  title: z.string().optional(),
  description: z.string().optional(),
  footer: z.string().optional(),
  mode: z.enum(["donut", "legend", "label"]).optional(),
});

export const scatterChartSchema = z.object({
  data: chartDataSchema,
  xKey: z.string(),
  yKey: z.string(),
  title: z.string().optional(),
  description: z.string().optional(),
  footer: z.string().optional(),
  labelKey: z.string().optional(),
});

export const radarChartSchema = z.object({
  data: chartDataSchema,
  angleKey: z.string(),
  valueKeys: z.union([z.array(z.string()), z.string()]),
  title: z.string().optional(),
  description: z.string().optional(),
  footer: z.string().optional(),
  colors: z.array(z.string()).optional(),
});

export const gaugeChartSchema = z.object({
  value: z.number(),
  title: z.string().optional(),
  min: z.number().optional(),
  max: z.number().optional(),
  unit: z.string().optional(),
  thresholds: z.object({ warning: z.number(), danger: z.number() }).optional(),
  variant: z.enum(["gauge", "text", "stacked"]).optional(),
  secondValue: z.number().optional(),
  secondLabel: z.string().optional(),
  size: z.enum(["sm", "md", "lg"]).optional(),
});

// ---------------------------------------------------------------------------
// Shared helpers
// ---------------------------------------------------------------------------

function ChartCard({
  title,
  description,
  footer,
  children,
}: {
  title?: string;
  description?: string;
  footer?: string;
  children: React.ReactNode;
}) {
  return (
    <ToolCard
      size="standard"
      title={title}
      subtitle={description}
      footer={
        footer ? <p className="text-xs text-zinc-500">{footer}</p> : undefined
      }
    >
      {children}
    </ToolCard>
  );
}

// ---------------------------------------------------------------------------
// Views
// ---------------------------------------------------------------------------

export function BarChartView(props: z.infer<typeof barChartSchema>) {
  const keys = toKeys(props.yKeys);
  const colors = props.colors ?? CHART_COLORS;
  const chartConfig: ChartConfig = Object.fromEntries(
    keys.map((key, i) => [
      key,
      { label: key, color: colors[i % colors.length] },
    ]),
  );

  const isStacked = props.variant === "stacked";
  const isHorizontal = props.variant === "horizontal";
  const alwaysLegend = props.variant === "multiple";
  const showLegend = alwaysLegend || keys.length > 1;

  return (
    <ChartCard
      title={props.title}
      description={props.description}
      footer={props.footer}
    >
      <ChartContainer
        config={chartConfig}
        className="aspect-auto h-[250px] w-full"
      >
        <RechartsBarChart
          data={props.data}
          layout={isHorizontal ? "vertical" : "horizontal"}
          margin={
            isHorizontal
              ? { top: 4, right: 48, bottom: 4, left: 4 }
              : { top: 20, right: 8, bottom: 4, left: 8 }
          }
        >
          <CartesianGrid
            strokeDasharray="3 3"
            stroke="#3f3f46"
            opacity={0.6}
            vertical={isHorizontal}
            horizontal={!isHorizontal}
          />
          {isHorizontal ? (
            <>
              <YAxis
                dataKey={props.xKey}
                type="category"
                axisLine={false}
                tickLine={false}
                tick={{ fill: "#71717a", fontSize: 11 }}
                width={88}
              />
              <XAxis
                type="number"
                axisLine={false}
                tickLine={false}
                tick={{ fill: "#71717a", fontSize: 11 }}
                tickFormatter={fmtNum}
              />
            </>
          ) : (
            <>
              <XAxis
                dataKey={props.xKey}
                axisLine={false}
                tickLine={false}
                tick={{ fill: "#71717a", fontSize: 11 }}
              />
              <YAxis
                axisLine={false}
                tickLine={false}
                tick={{ fill: "#71717a", fontSize: 11 }}
                tickFormatter={fmtNum}
                width={40}
              />
            </>
          )}
          <ChartTooltip
            cursor={{ fill: "rgba(255,255,255,0.04)" }}
            content={<ChartTooltipContent />}
          />
          {showLegend && <ChartLegend content={<ChartLegendContent />} />}
          {keys.map((key, ki) => (
            <Bar
              key={key}
              dataKey={key}
              fill={`var(--color-${key})`}
              radius={isStacked && ki < keys.length - 1 ? 0 : [6, 6, 0, 0]}
              maxBarSize={48}
              {...(isStacked ? { stackId: "stack" } : {})}
            >
              {!isStacked && !isHorizontal && keys.length === 1 && (
                <LabelList
                  dataKey={key}
                  position="top"
                  formatter={fmtNum}
                  className="fill-foreground"
                  fontSize={11}
                />
              )}
            </Bar>
          ))}
        </RechartsBarChart>
      </ChartContainer>
    </ChartCard>
  );
}

export function LineChartView(props: z.infer<typeof lineChartSchema>) {
  const keys = toKeys(props.yKeys);
  const colors = props.colors ?? CHART_COLORS;
  const chartConfig: ChartConfig = Object.fromEntries(
    keys.map((key, i) => [
      key,
      { label: key, color: colors[i % colors.length] },
    ]),
  );
  const showLegend = keys.length > 1;
  return (
    <ChartCard
      title={props.title}
      description={props.description}
      footer={props.footer}
    >
      <ChartContainer
        config={chartConfig}
        className="aspect-auto h-[250px] w-full"
      >
        <RechartsLineChart
          data={props.data}
          margin={{ top: 20, right: 12, bottom: 4, left: 8 }}
        >
          <CartesianGrid
            strokeDasharray="3 3"
            stroke="#3f3f46"
            opacity={0.6}
            vertical={false}
          />
          <XAxis
            dataKey={props.xKey}
            axisLine={false}
            tickLine={false}
            tick={{ fill: "#71717a", fontSize: 11 }}
          />
          <YAxis
            axisLine={false}
            tickLine={false}
            tick={{ fill: "#71717a", fontSize: 11 }}
            tickFormatter={fmtNum}
            width={40}
          />
          <ChartTooltip content={<ChartTooltipContent indicator="dot" />} />
          {showLegend && <ChartLegend content={<ChartLegendContent />} />}
          {keys.map((key) => (
            <Line
              key={key}
              type="monotone"
              dataKey={key}
              stroke={`var(--color-${key})`}
              strokeWidth={2}
              dot={
                props.showDots !== false
                  ? { fill: `var(--color-${key})` }
                  : false
              }
              activeDot={{ r: 6 }}
            >
              {props.showLabels === true && (
                <LabelList
                  position="top"
                  offset={12}
                  className="fill-foreground"
                  fontSize={12}
                  formatter={fmtNum}
                />
              )}
            </Line>
          ))}
        </RechartsLineChart>
      </ChartContainer>
    </ChartCard>
  );
}

export function AreaChartView(props: z.infer<typeof areaChartSchema>) {
  const keys = toKeys(props.yKeys);
  const colors = props.colors ?? CHART_COLORS;
  const chartConfig: ChartConfig = Object.fromEntries(
    keys.map((key, i) => [
      key,
      { label: key, color: colors[i % colors.length] },
    ]),
  );
  const showLegend = keys.length > 1;
  return (
    <ChartCard
      title={props.title}
      description={props.description}
      footer={props.footer}
    >
      <ChartContainer
        config={chartConfig}
        className="aspect-auto h-[250px] w-full"
      >
        <RechartsAreaChart
          data={props.data}
          margin={{ top: 8, right: 12, bottom: 4, left: 8 }}
        >
          <defs>
            {keys.map((key) => (
              <linearGradient
                key={key}
                id={`gradient-${key}`}
                x1="0"
                y1="0"
                x2="0"
                y2="1"
              >
                <stop
                  offset="5%"
                  stopColor={`var(--color-${key})`}
                  stopOpacity={0.8}
                />
                <stop
                  offset="95%"
                  stopColor={`var(--color-${key})`}
                  stopOpacity={0.1}
                />
              </linearGradient>
            ))}
          </defs>
          <CartesianGrid
            strokeDasharray="3 3"
            stroke="#3f3f46"
            opacity={0.6}
            vertical={false}
          />
          <XAxis
            dataKey={props.xKey}
            axisLine={false}
            tickLine={false}
            tick={{ fill: "#71717a", fontSize: 11 }}
          />
          <YAxis
            axisLine={false}
            tickLine={false}
            tick={{ fill: "#71717a", fontSize: 11 }}
            tickFormatter={fmtNum}
            width={40}
          />
          <ChartTooltip
            cursor={false}
            content={<ChartTooltipContent indicator="dot" />}
          />
          {showLegend && <ChartLegend content={<ChartLegendContent />} />}
          {keys.map((key) => (
            <Area
              key={key}
              type="natural"
              dataKey={key}
              stroke={`var(--color-${key})`}
              strokeWidth={2.5}
              fill={`url(#gradient-${key})`}
              fillOpacity={1}
              dot={false}
              activeDot={{ r: 5, strokeWidth: 0 }}
              stackId={keys.length > 1 ? "a" : undefined}
            />
          ))}
        </RechartsAreaChart>
      </ChartContainer>
    </ChartCard>
  );
}

export function PieChartView(props: z.infer<typeof pieChartSchema>) {
  const mode = props.mode ?? "donut";
  const chartConfig: ChartConfig = Object.fromEntries(
    props.data.map((entry, i) => {
      const name = String(entry[props.nameKey] ?? i);
      return [name, { label: name, color: PIE_COLORS[i % PIE_COLORS.length] }];
    }),
  );
  const total = React.useMemo(
    () =>
      props.data.reduce((sum, entry) => {
        const val = entry[props.valueKey];
        return sum + (typeof val === "number" ? val : 0);
      }, 0),
    [props.data, props.valueKey],
  );
  return (
    <ChartCard
      title={props.title}
      description={props.description}
      footer={props.footer}
    >
      <SquareChart
        config={chartConfig}
        className={
          mode === "label" ? "[&_.recharts-pie-label-text]:fill-foreground" : ""
        }
      >
        <RechartsPieChart>
          {mode === "donut" ? (
            <Pie
              data={props.data}
              dataKey={props.valueKey}
              nameKey={props.nameKey}
              cx="50%"
              cy="50%"
              outerRadius={80}
              innerRadius={60}
              paddingAngle={2}
              strokeWidth={5}
              stroke="#27272a"
            >
              {props.data.map((entry, i) => (
                <Cell
                  key={String(entry[props.nameKey])}
                  fill={PIE_COLORS[i % PIE_COLORS.length]}
                />
              ))}
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
                          className="fill-foreground text-2xl font-bold"
                        >
                          {fmtNum(total)}
                        </tspan>
                        {props.title && (
                          <tspan
                            x={viewBox.cx}
                            y={(viewBox.cy || 0) + 20}
                            fontSize={12}
                            fill="#71717a"
                          >
                            {props.title.length > 14
                              ? `${props.title.slice(0, 12)}…`
                              : props.title}
                          </tspan>
                        )}
                      </text>
                    );
                  }
                  return null;
                }}
              />
            </Pie>
          ) : mode === "label" ? (
            <Pie
              data={props.data}
              dataKey={props.valueKey}
              nameKey={props.nameKey}
              cx="50%"
              cy="50%"
              outerRadius={70}
              strokeWidth={0}
              label
            >
              {props.data.map((entry, i) => (
                <Cell
                  key={String(entry[props.nameKey])}
                  fill={PIE_COLORS[i % PIE_COLORS.length]}
                />
              ))}
            </Pie>
          ) : (
            <Pie
              data={props.data}
              dataKey={props.valueKey}
              nameKey={props.nameKey}
              cx="50%"
              cy="50%"
              outerRadius={70}
              strokeWidth={0}
            >
              {props.data.map((entry, i) => (
                <Cell
                  key={String(entry[props.nameKey])}
                  fill={PIE_COLORS[i % PIE_COLORS.length]}
                />
              ))}
            </Pie>
          )}
          <ChartTooltip
            content={<ChartTooltipContent nameKey={props.nameKey} />}
          />
          {mode === "legend" && (
            <ChartLegend
              content={<ChartLegendContent nameKey={props.nameKey} />}
              className="-translate-y-2 flex-wrap gap-2"
            />
          )}
        </RechartsPieChart>
      </SquareChart>
    </ChartCard>
  );
}

export function ScatterChartView(props: z.infer<typeof scatterChartSchema>) {
  const chartConfig: ChartConfig = {
    scatter: { label: "Data", color: CHART_COLORS[0] },
  };
  return (
    <ChartCard
      title={props.title}
      description={props.description}
      footer={props.footer}
    >
      <ChartContainer
        config={chartConfig}
        className="aspect-auto h-[250px] w-full"
      >
        <RechartsScatterChart
          margin={{ top: 20, right: 12, bottom: 4, left: 8 }}
        >
          <CartesianGrid strokeDasharray="3 3" stroke="#3f3f46" opacity={0.6} />
          <XAxis
            dataKey={props.xKey}
            name={props.xKey}
            axisLine={false}
            tickLine={false}
            tick={{ fill: "#71717a", fontSize: 11 }}
            tickFormatter={fmtNum}
          />
          <YAxis
            dataKey={props.yKey}
            name={props.yKey}
            axisLine={false}
            tickLine={false}
            tick={{ fill: "#71717a", fontSize: 11 }}
            tickFormatter={fmtNum}
            width={40}
          />
          <ChartTooltip
            cursor={{ strokeDasharray: "3 3" }}
            content={<ChartTooltipContent />}
          />
          <Scatter
            data={props.data}
            fill="var(--color-scatter)"
            fillOpacity={0.8}
          />
        </RechartsScatterChart>
      </ChartContainer>
    </ChartCard>
  );
}

export function RadarChartView(props: z.infer<typeof radarChartSchema>) {
  const keys = toKeys(props.valueKeys);
  const colors = props.colors ?? CHART_COLORS;
  const chartConfig: ChartConfig = Object.fromEntries(
    keys.map((key, i) => [
      key,
      { label: key, color: colors[i % colors.length] },
    ]),
  );
  const showLegend = keys.length > 1;
  return (
    <ChartCard
      title={props.title}
      description={props.description}
      footer={props.footer}
    >
      <SquareChart config={chartConfig} size={260}>
        <RechartsRadarChart data={props.data}>
          <PolarGrid stroke="#3f3f46" />
          <PolarAngleAxis
            dataKey={props.angleKey}
            tick={({ x, y, textAnchor, index, ...tickProps }) => {
              const d = props.data[index] as Record<string, string | number>;
              const yNum = typeof y === "number" ? y : 0;
              const vals = keys.map((k) => d[k]).join(" / ");
              return (
                <text
                  x={x}
                  y={yNum + (index === 0 ? -10 : 0)}
                  textAnchor={textAnchor}
                  fontSize={12}
                  {...tickProps}
                >
                  <tspan fill="#e4e4e7" fontWeight={500}>
                    {vals}
                  </tspan>
                  <tspan x={x} dy="1.1em" fontSize={11} fill="#71717a">
                    {String(d[props.angleKey])}
                  </tspan>
                </text>
              );
            }}
          />
          <ChartTooltip content={<ChartTooltipContent />} />
          {keys.map((key) => (
            <Radar
              key={key}
              dataKey={key}
              stroke={`var(--color-${key})`}
              strokeWidth={2}
              fill={`var(--color-${key})`}
              fillOpacity={0.2}
            />
          ))}
          {showLegend && <ChartLegend content={<ChartLegendContent />} />}
        </RechartsRadarChart>
      </SquareChart>
    </ChartCard>
  );
}

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

export const barChartDef = defineComponent({
  name: "BarChart",
  description: "Bar chart for comparisons and distributions.",
  props: barChartSchema,
  component: ({ props }) => React.createElement(BarChartView, props),
});

export const lineChartDef = defineComponent({
  name: "LineChart",
  description: "Line chart for trends over time.",
  props: lineChartSchema,
  component: ({ props }) => React.createElement(LineChartView, props),
});

export const areaChartDef = defineComponent({
  name: "AreaChart",
  description: "Filled area chart for cumulative values.",
  props: areaChartSchema,
  component: ({ props }) => React.createElement(AreaChartView, props),
});

export const pieChartDef = defineComponent({
  name: "PieChart",
  description: "Pie chart for proportions.",
  props: pieChartSchema,
  component: ({ props }) => React.createElement(PieChartView, props),
});

export const scatterChartDef = defineComponent({
  name: "ScatterChart",
  description: "Scatter chart for correlation between two variables.",
  props: scatterChartSchema,
  component: ({ props }) => React.createElement(ScatterChartView, props),
});

export const radarChartDef = defineComponent({
  name: "RadarChart",
  description: "Radar chart for multi-axis comparisons.",
  props: radarChartSchema,
  component: ({ props }) => React.createElement(RadarChartView, props),
});

export const gaugeChartDef = defineComponent({
  name: "GaugeChart",
  description: "Radial gauge for a value with min/max bounds.",
  props: gaugeChartSchema,
  component: ({ props }) => React.createElement(GaugeChartView, props),
});
