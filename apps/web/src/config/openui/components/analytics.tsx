import { Card, CardBody, CardFooter, CardHeader } from "@heroui/card";
import { ArrowDown01Icon, ArrowRight01Icon, ArrowUp01Icon } from "@icons";
import { defineComponent } from "@openuidev/react-lang";
import React from "react";
import {
  Area,
  Bar,
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

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const CHART_COLORS = ["#00bbff", "#34d399", "#60a5fa", "#f472b6", "#fb923c"];
const PIE_COLORS = ["#00bbff", "#34d399", "#60a5fa", "#a78bfa", "#f472b6"];

/** Coerce a string | string[] to string[] so charts never break on a bare string. */
function toKeys(v: string | string[]): string[] {
  return Array.isArray(v) ? v : [v];
}

// ---------------------------------------------------------------------------
// Schemas
// ---------------------------------------------------------------------------

export const statRowSchema = z.object({
  title: z.string(),
  value: z.union([z.string(), z.number()]),
  unit: z.string().optional(),
  trend: z.enum(["up", "down", "neutral"]).optional(),
  trendLabel: z.string().optional(),
});

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
});

// ---------------------------------------------------------------------------
// Shared helpers
// ---------------------------------------------------------------------------

const TREND_STYLES: Record<string, { color: string }> = {
  up: { color: "text-emerald-400" },
  down: { color: "text-red-400" },
  neutral: { color: "text-zinc-400" },
};

function TrendIcon({
  trend,
  className,
}: {
  trend: string;
  className?: string;
}) {
  if (trend === "up") return <ArrowUp01Icon className={className} />;
  if (trend === "down") return <ArrowDown01Icon className={className} />;
  return <ArrowRight01Icon className={className} />;
}

function ChartCard({
  title,
  description,
  footer,
  children,
  dataPoints = 0,
}: {
  title?: string;
  description?: string;
  footer?: string;
  children: React.ReactNode;
  dataPoints?: number;
}) {
  // Scale width to data: ~80px per point, min 300px, max 3xl (48rem)
  const width =
    dataPoints > 0 ? Math.min(768, Math.max(300, dataPoints * 80)) : undefined;
  return (
    <Card
      className="bg-zinc-800 border-none shadow-none max-w-3xl"
      style={width ? { width } : { width: "100%" }}
    >
      {(title || description) && (
        <CardHeader className="pb-0 flex-col items-start">
          {title && (
            <p className="text-sm font-semibold text-zinc-100">{title}</p>
          )}
          {description && (
            <p className="text-xs text-zinc-400">{description}</p>
          )}
        </CardHeader>
      )}
      <CardBody>{children}</CardBody>
      {footer && (
        <CardFooter>
          <p className="text-xs text-zinc-500">{footer}</p>
        </CardFooter>
      )}
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Views
// ---------------------------------------------------------------------------

export function StatRowView(props: z.infer<typeof statRowSchema>) {
  const trendStyle = props.trend ? TREND_STYLES[props.trend] : null;
  return (
    <div className="rounded-2xl bg-zinc-800 p-5 w-fit min-w-50 h-full flex flex-col justify-between">
      <p className="text-xs text-zinc-500 truncate">{props.title}</p>
      <div className="flex items-end gap-1.5">
        <span className="text-4xl font-bold text-zinc-100 leading-none">
          {props.value}
        </span>
        {props.unit && (
          <span className="text-sm text-zinc-500 mb-0.5">{props.unit}</span>
        )}
      </div>
      <div className="h-4 flex items-center">
        {trendStyle && props.trendLabel && props.trend ? (
          <div className={`flex items-center gap-1 ${trendStyle.color}`}>
            <TrendIcon
              trend={props.trend}
              className={`w-3.5 h-3.5 ${trendStyle.color}`}
            />
            <span className="text-xs font-medium">{props.trendLabel}</span>
          </div>
        ) : null}
      </div>
    </div>
  );
}

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
      dataPoints={props.data.length}
    >
      <ChartContainer config={chartConfig} className="h-50 w-full">
        <RechartsBarChart
          data={props.data}
          layout={isHorizontal ? "vertical" : "horizontal"}
        >
          {isHorizontal ? (
            <>
              <YAxis
                dataKey={props.xKey}
                type="category"
                axisLine={false}
                tickLine={false}
                tick={{ fill: "#71717a", fontSize: 11 }}
                width={80}
              />
              <XAxis
                type="number"
                axisLine={false}
                tickLine={false}
                tick={{ fill: "#71717a", fontSize: 11 }}
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
              />
            </>
          )}
          <ChartTooltip cursor={false} content={<ChartTooltipContent />} />
          {showLegend && <ChartLegend content={<ChartLegendContent />} />}
          {keys.map((key) => (
            <Bar
              key={key}
              dataKey={key}
              fill={`var(--color-${key})`}
              radius={8}
              maxBarSize={40}
              {...(isStacked ? { stackId: "stack" } : {})}
            />
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
      dataPoints={props.data.length}
    >
      <ChartContainer config={chartConfig} className="h-50 w-full">
        <RechartsLineChart
          data={props.data}
          {...(props.showLabels === true
            ? { margin: { top: 24, left: 12, right: 12 } }
            : {})}
        >
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
          />
          <ChartTooltip content={<ChartTooltipContent />} />
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
            >
              {props.showLabels === true && (
                <LabelList
                  position="top"
                  offset={12}
                  fontSize={12}
                  fill="#a1a1aa"
                  dataKey={props.xKey}
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
      dataPoints={props.data.length}
    >
      <ChartContainer config={chartConfig} className="h-50 w-full">
        <RechartsAreaChart data={props.data}>
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
                  offset="0%"
                  stopColor={`var(--color-${key})`}
                  stopOpacity={0.4}
                />
                <stop
                  offset="95%"
                  stopColor={`var(--color-${key})`}
                  stopOpacity={0.05}
                />
              </linearGradient>
            ))}
          </defs>
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
          />
          <ChartTooltip content={<ChartTooltipContent />} />
          {showLegend && <ChartLegend content={<ChartLegendContent />} />}
          {keys.map((key) => (
            <Area
              key={key}
              type="natural"
              dataKey={key}
              stroke={`var(--color-${key})`}
              strokeWidth={2}
              fill={`url(#gradient-${key})`}
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
      dataPoints={props.data.length}
    >
      <ChartContainer
        config={chartConfig}
        className={`h-50 w-full ${mode === "label" ? "[&_.recharts-pie-label-text]:fill-foreground" : ""}`}
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
              strokeWidth={0}
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
                          {total}
                        </tspan>
                        <tspan
                          x={viewBox.cx}
                          y={(viewBox.cy || 0) + 20}
                          fontSize={12}
                          fill="#71717a"
                        >
                          {props.valueKey}
                        </tspan>
                      </text>
                    );
                  }
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
      </ChartContainer>
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
      dataPoints={props.data.length}
    >
      <ChartContainer config={chartConfig} className="h-50 w-full">
        <RechartsScatterChart>
          <XAxis
            dataKey={props.xKey}
            axisLine={false}
            tickLine={false}
            tick={{ fill: "#71717a", fontSize: 11 }}
          />
          <YAxis
            dataKey={props.yKey}
            axisLine={false}
            tickLine={false}
            tick={{ fill: "#71717a", fontSize: 11 }}
          />
          <ChartTooltip content={<ChartTooltipContent />} />
          <Scatter data={props.data} fill="var(--color-scatter)" />
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
      dataPoints={props.data.length}
    >
      <ChartContainer config={chartConfig} className="h-55 w-full">
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
      </ChartContainer>
    </ChartCard>
  );
}

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

  if (variant === "text") {
    const textChartConfig: ChartConfig = {
      value: { label: props.title ?? "Value", color },
    };
    const textData = [{ name: "value", value: pct, fill: color }];
    return (
      <div className="rounded-2xl bg-zinc-800 p-4 text-center">
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
                }}
              />
            </PolarRadiusAxis>
          </RadialBarChart>
        </ChartContainer>
      </div>
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
    return (
      <div className="rounded-2xl bg-zinc-800 p-4 text-center">
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
                }}
              />
            </PolarRadiusAxis>
          </RadialBarChart>
        </ChartContainer>
      </div>
    );
  }

  // Default: "gauge" variant — radial chart with PolarGrid track ring
  // PolarGrid draws the full ring as background track; endAngle is proportional to fill
  const maxArc = 250;
  const valueAngle = Math.max(1, (pct / 100) * maxArc);
  const outerR = 65;
  const innerR = 55;

  const gaugeConfig: ChartConfig = {
    value: { label: props.title ?? "Value", color },
  };
  const gaugeData = [{ name: "value", value: 1, fill: color }];

  return (
    <div
      className="rounded-2xl bg-zinc-800 p-4 text-center"
      style={{ width: 200 }}
    >
      <ChartContainer
        config={gaugeConfig}
        className="mx-auto h-[160px] w-[160px]"
      >
        <RadialBarChart
          data={gaugeData}
          startAngle={0}
          endAngle={valueAngle}
          outerRadius={outerR}
          innerRadius={innerR}
        >
          <PolarGrid
            gridType="circle"
            radialLines={false}
            stroke="none"
            className="first:fill-zinc-700 last:fill-zinc-800"
            polarRadius={[outerR, innerR]}
          />
          <RadialBar dataKey="value" cornerRadius={10} />
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
              }}
            />
          </PolarRadiusAxis>
        </RadialBarChart>
      </ChartContainer>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Component definitions
// ---------------------------------------------------------------------------

export const statRowDef = defineComponent({
  name: "StatRow",
  description: "Single KPI with optional trend.",
  props: statRowSchema,
  component: ({ props }) => React.createElement(StatRowView, props),
});

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
