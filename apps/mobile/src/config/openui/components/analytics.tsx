import { ArrowDown01Icon, ArrowRight01Icon, ArrowUp01Icon } from "@icons";
import { defineComponent } from "@openuidev/react-lang";
import React from "react";
import { View } from "react-native";
import Svg, {
  Circle,
  Defs,
  G,
  Line,
  LinearGradient,
  Path,
  Polygon,
  Rect,
  Stop,
  Text as SvgText,
} from "react-native-svg";
import { z } from "zod";
import { Text } from "@/components/ui/text";
import { Card, MutedText, SectionTitle } from "./primitives";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const CHART_COLORS = ["#00bbff", "#34d399", "#60a5fa", "#f472b6", "#fb923c"];
const PIE_COLORS = ["#00bbff", "#34d399", "#60a5fa", "#a78bfa", "#f472b6"];
const GRID_COLOR = "#3f3f46";
const AXIS_COLOR = "#71717a";
const LEGEND_LABEL_COLOR = "#a1a1aa";
const SLICE_STROKE = "#27272a";
const CHART_HEIGHT = 200;
const PIE_HEIGHT = 220;
const RADAR_HEIGHT = 220;
const GAUGE_HEIGHT = 180;

const AXIS_FONT = 10;
const LABEL_FONT = 10;
const LEGEND_FONT = 12;
const FOOTER_FONT = 12;
const STAT_FONT = 30;
const TICK_COUNT = 4; // 4 intervals → 5 grid lines

const TREND_COLOR: Record<string, string> = {
  up: "#34d399",
  down: "#f87171",
  neutral: "#a1a1aa",
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function toKeys(v: string | string[]): string[] {
  return Array.isArray(v) ? v : [v];
}

function toNumber(v: string | number | undefined): number {
  if (typeof v === "number") return v;
  if (typeof v === "string") {
    const n = Number.parseFloat(v);
    return Number.isFinite(n) ? n : 0;
  }
  return 0;
}

function formatTick(v: number): string {
  if (Math.abs(v) >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`;
  if (Math.abs(v) >= 1_000) return `${(v / 1_000).toFixed(1)}K`;
  return v % 1 === 0 ? String(v) : v.toFixed(1);
}

function truncate(s: string, n = 8): string {
  return s.length <= n ? s : `${s.slice(0, n - 1)}…`;
}

// ---------------------------------------------------------------------------
// Schemas — MUST stay byte-for-byte identical to web
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
// Shared UI primitives
// ---------------------------------------------------------------------------

interface LegendEntry {
  label: string;
  color: string;
  sublabel?: string;
}

function Legend({ entries }: { entries: LegendEntry[] }) {
  return (
    <View className="flex-row flex-wrap mt-3" style={{ gap: 12 }}>
      {entries.map((entry) => (
        <View
          key={entry.label}
          style={{ flexDirection: "row", alignItems: "center", gap: 6 }}
        >
          <View
            style={{
              width: 8,
              height: 8,
              borderRadius: 4,
              backgroundColor: entry.color,
            }}
          />
          <Text className="text-zinc-400" style={{ fontSize: LEGEND_FONT }}>
            {entry.label}
          </Text>
          {entry.sublabel ? (
            <Text className="text-zinc-500" style={{ fontSize: LEGEND_FONT }}>
              {entry.sublabel}
            </Text>
          ) : null}
        </View>
      ))}
    </View>
  );
}

interface ChartShellProps {
  title?: string;
  description?: string;
  footer?: string;
  height: number;
  children: (width: number) => React.ReactNode;
  legend?: React.ReactNode;
}

function ChartShell({
  title,
  description,
  footer,
  height,
  children,
  legend,
}: ChartShellProps) {
  const [width, setWidth] = React.useState(0);
  return (
    <Card>
      {title ? <SectionTitle>{title}</SectionTitle> : null}
      {description ? (
        <View className="mb-2">
          <MutedText>{description}</MutedText>
        </View>
      ) : null}
      <View
        onLayout={(e) => setWidth(e.nativeEvent.layout.width)}
        style={{ width: "100%", height }}
      >
        {width > 0 ? children(width) : null}
      </View>
      {legend}
      {footer ? (
        <View className="mt-2">
          <Text className="text-zinc-500" style={{ fontSize: FOOTER_FONT }}>
            {footer}
          </Text>
        </View>
      ) : null}
    </Card>
  );
}

// ---------------------------------------------------------------------------
// StatRow
// ---------------------------------------------------------------------------

export function StatRowView(props: z.infer<typeof statRowSchema>) {
  const trend = props.trend;
  const trendColor = trend ? TREND_COLOR[trend] : TREND_COLOR.neutral;
  const TrendIcon =
    trend === "up"
      ? ArrowUp01Icon
      : trend === "down"
        ? ArrowDown01Icon
        : ArrowRight01Icon;

  return (
    <Card>
      <SectionTitle>{props.title}</SectionTitle>
      <View
        style={{
          flexDirection: "row",
          alignItems: "flex-end",
          gap: 6,
        }}
      >
        <Text
          className="text-zinc-100"
          style={{
            fontSize: STAT_FONT,
            fontWeight: "600",
            lineHeight: STAT_FONT + 2,
          }}
        >
          {props.value}
        </Text>
        {props.unit ? (
          <Text
            className="text-zinc-500"
            style={{ fontSize: 14, marginBottom: 4 }}
          >
            {props.unit}
          </Text>
        ) : null}
      </View>
      {trend && props.trendLabel ? (
        <View
          className="mt-2"
          style={{
            flexDirection: "row",
            alignItems: "center",
            gap: 4,
          }}
        >
          <TrendIcon size={14} color={trendColor} />
          <Text
            style={{
              color: trendColor,
              fontSize: 12,
              fontWeight: "500",
            }}
          >
            {props.trendLabel}
          </Text>
        </View>
      ) : null}
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Axis/grid helper — shared by bar, line, area, scatter
// ---------------------------------------------------------------------------

interface AxisGridProps {
  padLeft: number;
  padRight: number;
  padTop: number;
  plotH: number;
  width: number;
  minVal: number;
  maxVal: number;
  tickCount?: number;
  horizontal?: boolean;
}

function AxisGrid({
  padLeft,
  padRight,
  padTop,
  plotH,
  width,
  minVal,
  maxVal,
  tickCount = TICK_COUNT,
  horizontal = false,
}: AxisGridProps) {
  const range = Math.max(maxVal - minVal, 1);
  const ticks = Array.from(
    { length: tickCount + 1 },
    (_, i) => minVal + (range * i) / tickCount,
  );
  if (horizontal) {
    // Vertical grid lines for horizontal bar charts.
    const plotW = width - padLeft - padRight;
    return (
      <G>
        {ticks.map((tick) => {
          const x = padLeft + ((tick - minVal) / range) * plotW;
          return (
            <G key={`grid-${tick}`}>
              <Line
                x1={x}
                y1={padTop}
                x2={x}
                y2={padTop + plotH}
                stroke={GRID_COLOR}
                strokeWidth={1}
                strokeDasharray="3 3"
              />
              <SvgText
                x={x}
                y={padTop + plotH + 14}
                fontSize={AXIS_FONT}
                fill={AXIS_COLOR}
                textAnchor="middle"
              >
                {formatTick(tick)}
              </SvgText>
            </G>
          );
        })}
      </G>
    );
  }
  return (
    <G>
      {ticks.map((tick) => {
        const y = padTop + plotH - ((tick - minVal) / range) * plotH;
        return (
          <G key={`grid-${tick}`}>
            <Line
              x1={padLeft}
              y1={y}
              x2={width - padRight}
              y2={y}
              stroke={GRID_COLOR}
              strokeWidth={1}
              strokeDasharray="3 3"
            />
            <SvgText
              x={padLeft - 6}
              y={y + 3}
              fontSize={AXIS_FONT}
              fill={AXIS_COLOR}
              textAnchor="end"
            >
              {formatTick(tick)}
            </SvgText>
          </G>
        );
      })}
    </G>
  );
}

// ---------------------------------------------------------------------------
// BarChart
// ---------------------------------------------------------------------------

export function BarChartView(props: z.infer<typeof barChartSchema>) {
  const keys = toKeys(props.yKeys);
  const colors = props.colors ?? CHART_COLORS;
  const variant = props.variant ?? "default";
  const isHorizontal = variant === "horizontal";
  const alwaysLegend = variant === "multiple";
  const showLegend = alwaysLegend || keys.length > 1;
  const legendEntries = React.useMemo<LegendEntry[]>(
    () =>
      keys.map((key, i) => ({ label: key, color: colors[i % colors.length] })),
    [keys, colors],
  );
  const maxVal = React.useMemo(
    () =>
      Math.max(
        ...props.data.flatMap((d) => keys.map((k) => toNumber(d[k]))),
        1,
      ),
    [props.data, keys],
  );

  const renderVertical = (width: number) => {
    const padLeft = 40;
    const padRight = 10;
    const padTop = 10;
    const padBottom = 30;
    const plotW = Math.max(width - padLeft - padRight, 1);
    const plotH = CHART_HEIGHT - padTop - padBottom;
    const groupCount = Math.max(props.data.length, 1);
    const groupWidth = plotW / groupCount;
    // Bars occupy ~65% of the category slot (design contract: 60–70%)
    const usableGroupW = Math.max(groupWidth * 0.65, 4);
    const innerGap = 4;
    const barsPerGroup = Math.max(keys.length, 1);
    const barWidth = Math.max(
      2,
      (usableGroupW - innerGap * (barsPerGroup - 1)) / barsPerGroup,
    );
    const showAllLabels = groupCount <= 6;
    const labelEvery = showAllLabels ? 1 : Math.ceil(groupCount / 6);
    const rotateLabels = groupCount > 6;

    return (
      <Svg width={width} height={CHART_HEIGHT}>
        <AxisGrid
          padLeft={padLeft}
          padRight={padRight}
          padTop={padTop}
          plotH={plotH}
          width={width}
          minVal={0}
          maxVal={maxVal}
        />
        {props.data.map((row, i) => {
          const groupStart =
            padLeft + i * groupWidth + (groupWidth - usableGroupW) / 2;
          const groupCenter = padLeft + i * groupWidth + groupWidth / 2;
          const showLabel = i % labelEvery === 0 || i === props.data.length - 1;
          const raw = String(row[props.xKey]);
          const label = rotateLabels ? truncate(raw, 6) : truncate(raw, 9);
          return (
            <G key={`group-${String(row[props.xKey])}-${i}`}>
              {keys.map((key, ki) => {
                const val = toNumber(row[key]);
                const h = (val / maxVal) * plotH;
                const x = groupStart + ki * (barWidth + innerGap);
                const y = padTop + plotH - h;
                return (
                  <Rect
                    key={key}
                    x={x}
                    y={y}
                    width={barWidth}
                    height={Math.max(h, 0)}
                    rx={4}
                    ry={4}
                    fill={colors[ki % colors.length]}
                  />
                );
              })}
              {showLabel ? (
                rotateLabels ? (
                  <SvgText
                    x={groupCenter}
                    y={padTop + plotH + 14}
                    fontSize={AXIS_FONT}
                    fill={AXIS_COLOR}
                    textAnchor="end"
                    transform={`rotate(-35 ${groupCenter} ${padTop + plotH + 14})`}
                  >
                    {label}
                  </SvgText>
                ) : (
                  <SvgText
                    x={groupCenter}
                    y={padTop + plotH + 16}
                    fontSize={AXIS_FONT}
                    fill={AXIS_COLOR}
                    textAnchor="middle"
                  >
                    {label}
                  </SvgText>
                )
              ) : null}
            </G>
          );
        })}
      </Svg>
    );
  };

  const renderHorizontal = (width: number) => {
    const padLeft = 30;
    const padRight = 12;
    const padTop = 10;
    const padBottom = 40;
    const plotW = Math.max(width - padLeft - padRight, 1);
    const plotH = CHART_HEIGHT - padTop - padBottom;
    const groupCount = Math.max(props.data.length, 1);
    const groupHeight = plotH / groupCount;
    const usableGroupH = Math.max(groupHeight * 0.65, 4);
    const innerGap = 4;
    const barsPerGroup = Math.max(keys.length, 1);
    const barHeight = Math.max(
      2,
      (usableGroupH - innerGap * (barsPerGroup - 1)) / barsPerGroup,
    );

    return (
      <Svg width={width} height={CHART_HEIGHT}>
        <AxisGrid
          padLeft={padLeft}
          padRight={padRight}
          padTop={padTop}
          plotH={plotH}
          width={width}
          minVal={0}
          maxVal={maxVal}
          horizontal
        />
        {props.data.map((row, i) => {
          const groupStart =
            padTop + i * groupHeight + (groupHeight - usableGroupH) / 2;
          const groupCenter = padTop + i * groupHeight + groupHeight / 2;
          return (
            <G key={`group-${String(row[props.xKey])}-${i}`}>
              {keys.map((key, ki) => {
                const val = toNumber(row[key]);
                const w = (val / maxVal) * plotW;
                const y = groupStart + ki * (barHeight + innerGap);
                return (
                  <Rect
                    key={key}
                    x={padLeft}
                    y={y}
                    width={Math.max(w, 0)}
                    height={barHeight}
                    rx={4}
                    ry={4}
                    fill={colors[ki % colors.length]}
                  />
                );
              })}
              <SvgText
                x={padLeft - 6}
                y={groupCenter + 3}
                fontSize={AXIS_FONT}
                fill={AXIS_COLOR}
                textAnchor="end"
              >
                {truncate(String(row[props.xKey]), 6)}
              </SvgText>
            </G>
          );
        })}
      </Svg>
    );
  };

  return (
    <ChartShell
      title={props.title}
      description={props.description}
      footer={props.footer}
      height={CHART_HEIGHT}
      legend={showLegend ? <Legend entries={legendEntries} /> : null}
    >
      {isHorizontal ? renderHorizontal : renderVertical}
    </ChartShell>
  );
}

// ---------------------------------------------------------------------------
// LineChart
// ---------------------------------------------------------------------------

export function LineChartView(props: z.infer<typeof lineChartSchema>) {
  const keys = toKeys(props.yKeys);
  const colors = props.colors ?? CHART_COLORS;
  const showLegend = keys.length > 1;
  const legendEntries = React.useMemo<LegendEntry[]>(
    () =>
      keys.map((key, i) => ({ label: key, color: colors[i % colors.length] })),
    [keys, colors],
  );
  const { minVal, maxVal } = React.useMemo(() => {
    const allValues = props.data.flatMap((d) =>
      keys.map((k) => toNumber(d[k])),
    );
    return {
      minVal: Math.min(...allValues, 0),
      maxVal: Math.max(...allValues, 1),
    };
  }, [props.data, keys]);

  const render = (width: number) => {
    const padLeft = 40;
    const padRight = 10;
    const padTop = props.showLabels === true ? 20 : 10;
    const padBottom = 30;
    const plotW = Math.max(width - padLeft - padRight, 1);
    const plotH = CHART_HEIGHT - padTop - padBottom;
    const step = plotW / Math.max(props.data.length - 1, 1);
    const range = Math.max(maxVal - minVal, 1);
    const labelEvery = Math.ceil(props.data.length / 6);

    return (
      <Svg width={width} height={CHART_HEIGHT}>
        <AxisGrid
          padLeft={padLeft}
          padRight={padRight}
          padTop={padTop}
          plotH={plotH}
          width={width}
          minVal={minVal}
          maxVal={maxVal}
        />
        {keys.map((key, ki) => {
          const color = colors[ki % colors.length];
          const pts = props.data.map((row, i) => {
            const x = padLeft + i * step;
            const y =
              padTop + plotH - ((toNumber(row[key]) - minVal) / range) * plotH;
            return { x, y };
          });
          const d = pts
            .map((p, i) => `${i === 0 ? "M" : "L"} ${p.x} ${p.y}`)
            .join(" ");
          return (
            <G key={key}>
              <Path
                d={d}
                stroke={color}
                strokeWidth={2}
                fill="none"
                strokeLinejoin="round"
                strokeLinecap="round"
              />
              {props.showDots !== false
                ? pts.map((p, i) => (
                    <Circle
                      // biome-ignore lint/suspicious/noArrayIndexKey: point order stable
                      key={`${key}-dot-${i}`}
                      cx={p.x}
                      cy={p.y}
                      r={3}
                      fill={color}
                      stroke={color}
                      strokeWidth={2}
                    />
                  ))
                : null}
              {props.showLabels === true
                ? pts.map((p, i) => (
                    <SvgText
                      // biome-ignore lint/suspicious/noArrayIndexKey: label order stable
                      key={`${key}-label-${i}`}
                      x={p.x}
                      y={p.y - 10}
                      fontSize={LABEL_FONT}
                      fill={LEGEND_LABEL_COLOR}
                      textAnchor="middle"
                    >
                      {formatTick(toNumber(props.data[i][key]))}
                    </SvgText>
                  ))
                : null}
            </G>
          );
        })}
        {props.data.map((row, i) => {
          if (i % labelEvery !== 0 && i !== props.data.length - 1) return null;
          return (
            <SvgText
              // biome-ignore lint/suspicious/noArrayIndexKey: label index stable
              key={`xlabel-${i}`}
              x={padLeft + i * step}
              y={padTop + plotH + 16}
              fontSize={AXIS_FONT}
              fill={AXIS_COLOR}
              textAnchor="middle"
            >
              {truncate(String(row[props.xKey]), 9)}
            </SvgText>
          );
        })}
      </Svg>
    );
  };

  return (
    <ChartShell
      title={props.title}
      description={props.description}
      footer={props.footer}
      height={CHART_HEIGHT}
      legend={showLegend ? <Legend entries={legendEntries} /> : null}
    >
      {render}
    </ChartShell>
  );
}

// ---------------------------------------------------------------------------
// AreaChart
// ---------------------------------------------------------------------------

export function AreaChartView(props: z.infer<typeof areaChartSchema>) {
  const keys = toKeys(props.yKeys);
  const colors = props.colors ?? CHART_COLORS;
  const showLegend = keys.length > 1;
  const legendEntries = React.useMemo<LegendEntry[]>(
    () =>
      keys.map((key, i) => ({ label: key, color: colors[i % colors.length] })),
    [keys, colors],
  );
  // Unique gradient id prefix per instance to avoid SVG id collisions
  // when multiple area charts render on the same page.
  const uid = React.useId();
  const { minVal, maxVal } = React.useMemo(() => {
    const allValues = props.data.flatMap((d) =>
      keys.map((k) => toNumber(d[k])),
    );
    return {
      minVal: Math.min(...allValues, 0),
      maxVal: Math.max(...allValues, 1),
    };
  }, [props.data, keys]);

  const render = (width: number) => {
    const padLeft = 40;
    const padRight = 10;
    const padTop = 10;
    const padBottom = 30;
    const plotW = Math.max(width - padLeft - padRight, 1);
    const plotH = CHART_HEIGHT - padTop - padBottom;
    const step = plotW / Math.max(props.data.length - 1, 1);
    const range = Math.max(maxVal - minVal, 1);
    const baseY = padTop + plotH;
    const labelEvery = Math.ceil(props.data.length / 6);

    return (
      <Svg width={width} height={CHART_HEIGHT}>
        <Defs>
          {keys.map((key, ki) => (
            <LinearGradient
              key={key}
              id={`area-grad-${uid}-${ki}`}
              x1="0"
              y1="0"
              x2="0"
              y2="1"
            >
              <Stop
                offset="0%"
                stopColor={colors[ki % colors.length]}
                stopOpacity={0.3}
              />
              <Stop
                offset="100%"
                stopColor={colors[ki % colors.length]}
                stopOpacity={0}
              />
            </LinearGradient>
          ))}
        </Defs>
        <AxisGrid
          padLeft={padLeft}
          padRight={padRight}
          padTop={padTop}
          plotH={plotH}
          width={width}
          minVal={minVal}
          maxVal={maxVal}
        />
        {keys.map((key, ki) => {
          const color = colors[ki % colors.length];
          const pts = props.data.map((row, i) => {
            const x = padLeft + i * step;
            const y =
              padTop + plotH - ((toNumber(row[key]) - minVal) / range) * plotH;
            return { x, y };
          });
          if (pts.length === 0) return null;
          const line = pts
            .map((p, i) => `${i === 0 ? "M" : "L"} ${p.x} ${p.y}`)
            .join(" ");
          const fill = `${line} L ${pts[pts.length - 1].x} ${baseY} L ${pts[0].x} ${baseY} Z`;
          return (
            <G key={key}>
              <Path d={fill} fill={`url(#area-grad-${uid}-${ki})`} />
              <Path
                d={line}
                stroke={color}
                strokeWidth={2}
                fill="none"
                strokeLinejoin="round"
                strokeLinecap="round"
              />
            </G>
          );
        })}
        {props.data.map((row, i) => {
          if (i % labelEvery !== 0 && i !== props.data.length - 1) return null;
          return (
            <SvgText
              // biome-ignore lint/suspicious/noArrayIndexKey: label index stable
              key={`xlabel-${i}`}
              x={padLeft + i * step}
              y={padTop + plotH + 16}
              fontSize={AXIS_FONT}
              fill={AXIS_COLOR}
              textAnchor="middle"
            >
              {truncate(String(row[props.xKey]), 9)}
            </SvgText>
          );
        })}
      </Svg>
    );
  };

  return (
    <ChartShell
      title={props.title}
      description={props.description}
      footer={props.footer}
      height={CHART_HEIGHT}
      legend={showLegend ? <Legend entries={legendEntries} /> : null}
    >
      {render}
    </ChartShell>
  );
}

// ---------------------------------------------------------------------------
// PieChart
// ---------------------------------------------------------------------------

function describeArc(
  cx: number,
  cy: number,
  outerR: number,
  innerR: number,
  start: number,
  end: number,
): string {
  const x1 = cx + outerR * Math.cos(start);
  const y1 = cy + outerR * Math.sin(start);
  const x2 = cx + outerR * Math.cos(end);
  const y2 = cy + outerR * Math.sin(end);
  const largeArc = end - start > Math.PI ? 1 : 0;
  if (innerR <= 0) {
    return [
      `M ${cx} ${cy}`,
      `L ${x1} ${y1}`,
      `A ${outerR} ${outerR} 0 ${largeArc} 1 ${x2} ${y2}`,
      "Z",
    ].join(" ");
  }
  const ix1 = cx + innerR * Math.cos(end);
  const iy1 = cy + innerR * Math.sin(end);
  const ix2 = cx + innerR * Math.cos(start);
  const iy2 = cy + innerR * Math.sin(start);
  return [
    `M ${x1} ${y1}`,
    `A ${outerR} ${outerR} 0 ${largeArc} 1 ${x2} ${y2}`,
    `L ${ix1} ${iy1}`,
    `A ${innerR} ${innerR} 0 ${largeArc} 0 ${ix2} ${iy2}`,
    "Z",
  ].join(" ");
}

export function PieChartView(props: z.infer<typeof pieChartSchema>) {
  const mode = props.mode;
  const total = React.useMemo(
    () => props.data.reduce((sum, d) => sum + toNumber(d[props.valueKey]), 0),
    [props.data, props.valueKey],
  );

  const render = (width: number) => {
    const cx = width / 2;
    const cy = PIE_HEIGHT / 2;
    // Target diameter 160–180; clamp to available width.
    const maxR = mode === "label" ? 70 : 85;
    const outerR = Math.max(Math.min(maxR, cx - 24, cy - 24), 20);
    const innerR = mode === "donut" ? outerR * 0.5 : 0;
    let angle = -Math.PI / 2;

    return (
      <Svg width={width} height={PIE_HEIGHT}>
        {props.data.map((row, i) => {
          const val = toNumber(row[props.valueKey]);
          const frac = total > 0 ? val / total : 1 / props.data.length;
          const start = angle;
          const end = angle + frac * 2 * Math.PI;
          angle = end;
          const mid = (start + end) / 2;
          const color = PIE_COLORS[i % PIE_COLORS.length];
          const labelR = outerR + 14;
          const labelX = cx + labelR * Math.cos(mid);
          const labelY = cy + labelR * Math.sin(mid);
          // Leader line from slice edge to label position
          const leaderStartX = cx + outerR * Math.cos(mid);
          const leaderStartY = cy + outerR * Math.sin(mid);
          const leaderEndX = cx + (outerR + 6) * Math.cos(mid);
          const leaderEndY = cy + (outerR + 6) * Math.sin(mid);
          return (
            // biome-ignore lint/suspicious/noArrayIndexKey: slice order stable
            <G key={`slice-${i}`}>
              <Path
                d={describeArc(cx, cy, outerR, innerR, start, end)}
                fill={color}
                stroke={SLICE_STROKE}
                strokeWidth={2}
              />
              {mode === "label" ? (
                <>
                  <Line
                    x1={leaderStartX}
                    y1={leaderStartY}
                    x2={leaderEndX}
                    y2={leaderEndY}
                    stroke={LEGEND_LABEL_COLOR}
                    strokeWidth={1}
                  />
                  <SvgText
                    x={labelX}
                    y={labelY + 3}
                    fontSize={LABEL_FONT}
                    fill={LEGEND_LABEL_COLOR}
                    textAnchor={
                      Math.cos(mid) > 0.1
                        ? "start"
                        : Math.cos(mid) < -0.1
                          ? "end"
                          : "middle"
                    }
                  >
                    {`${truncate(String(row[props.nameKey]), 10)} ${formatTick(val)}`}
                  </SvgText>
                </>
              ) : null}
            </G>
          );
        })}
        {mode === "donut" ? (
          <G>
            <SvgText
              x={cx}
              y={cy - 2}
              fontSize={24}
              fontWeight="600"
              fill="#e4e4e7"
              textAnchor="middle"
            >
              {formatTick(total)}
            </SvgText>
            <SvgText
              x={cx}
              y={cy + 16}
              fontSize={LABEL_FONT}
              fill={AXIS_COLOR}
              textAnchor="middle"
            >
              {props.valueKey}
            </SvgText>
          </G>
        ) : null}
      </Svg>
    );
  };

  // Default mode (undefined) → solid slices + bottom legend.
  // mode === "legend" → explicit bottom legend with name/value/percent.
  const showLegend = mode === "legend" || mode === undefined;
  const legend = showLegend ? (
    <Legend
      entries={props.data.map((d, i) => {
        const val = toNumber(d[props.valueKey]);
        const pct = total > 0 ? `${((val / total) * 100).toFixed(0)}%` : "";
        return {
          label: `${String(d[props.nameKey])}: ${formatTick(val)}`,
          sublabel: pct ? `(${pct})` : undefined,
          color: PIE_COLORS[i % PIE_COLORS.length],
        };
      })}
    />
  ) : null;

  return (
    <ChartShell
      title={props.title}
      description={props.description}
      footer={props.footer}
      height={PIE_HEIGHT}
      legend={legend}
    >
      {render}
    </ChartShell>
  );
}

// ---------------------------------------------------------------------------
// ScatterChart
// ---------------------------------------------------------------------------

export function ScatterChartView(props: z.infer<typeof scatterChartSchema>) {
  const { xMin, xMax, yMin, yMax } = React.useMemo(() => {
    const xs = props.data.map((d) => toNumber(d[props.xKey]));
    const ys = props.data.map((d) => toNumber(d[props.yKey]));
    return {
      xMin: Math.min(...xs, 0),
      xMax: Math.max(...xs, 1),
      yMin: Math.min(...ys, 0),
      yMax: Math.max(...ys, 1),
    };
  }, [props.data, props.xKey, props.yKey]);

  const render = (width: number) => {
    const padLeft = 40;
    const padRight = 10;
    const padTop = 10;
    const padBottom = 30;
    const plotW = Math.max(width - padLeft - padRight, 1);
    const plotH = CHART_HEIGHT - padTop - padBottom;
    const xRange = Math.max(xMax - xMin, 1);
    const yRange = Math.max(yMax - yMin, 1);
    // 5 X ticks (including endpoints)
    const xTicks = Array.from(
      { length: TICK_COUNT + 1 },
      (_, i) => xMin + (xRange * i) / TICK_COUNT,
    );

    return (
      <Svg width={width} height={CHART_HEIGHT}>
        <AxisGrid
          padLeft={padLeft}
          padRight={padRight}
          padTop={padTop}
          plotH={plotH}
          width={width}
          minVal={yMin}
          maxVal={yMax}
        />
        {props.data.map((row, i) => {
          const x =
            padLeft + ((toNumber(row[props.xKey]) - xMin) / xRange) * plotW;
          const y =
            padTop +
            plotH -
            ((toNumber(row[props.yKey]) - yMin) / yRange) * plotH;
          const label = props.labelKey ? String(row[props.labelKey] ?? "") : "";
          return (
            // biome-ignore lint/suspicious/noArrayIndexKey: scatter point order stable
            <G key={`pt-${i}`}>
              <Circle
                cx={x}
                cy={y}
                r={4}
                fill={CHART_COLORS[0]}
                stroke="#ffffff"
                strokeOpacity={0.5}
                strokeWidth={1}
              />
              {label ? (
                <SvgText
                  x={x + 8}
                  y={y - 4}
                  fontSize={LABEL_FONT}
                  fill={LEGEND_LABEL_COLOR}
                  textAnchor="start"
                >
                  {truncate(label, 10)}
                </SvgText>
              ) : null}
            </G>
          );
        })}
        {xTicks.map((tick, i) => {
          const x = padLeft + ((tick - xMin) / xRange) * plotW;
          const anchor =
            i === 0 ? "start" : i === xTicks.length - 1 ? "end" : "middle";
          return (
            <SvgText
              key={`xtick-${tick}`}
              x={x}
              y={padTop + plotH + 16}
              fontSize={AXIS_FONT}
              fill={AXIS_COLOR}
              textAnchor={anchor}
            >
              {formatTick(tick)}
            </SvgText>
          );
        })}
      </Svg>
    );
  };

  return (
    <ChartShell
      title={props.title}
      description={props.description}
      footer={props.footer}
      height={CHART_HEIGHT}
    >
      {render}
    </ChartShell>
  );
}

// ---------------------------------------------------------------------------
// RadarChart
// ---------------------------------------------------------------------------

export function RadarChartView(props: z.infer<typeof radarChartSchema>) {
  const keys = toKeys(props.valueKeys);
  const colors = props.colors ?? CHART_COLORS;
  const showLegend = keys.length > 1;
  const legendEntries = React.useMemo<LegendEntry[]>(
    () =>
      keys.map((key, i) => ({ label: key, color: colors[i % colors.length] })),
    [keys, colors],
  );
  const axes = props.data.length;
  const maxVal = React.useMemo(
    () =>
      Math.max(
        ...props.data.flatMap((d) => keys.map((k) => toNumber(d[k]))),
        1,
      ),
    [props.data, keys],
  );

  const render = (width: number) => {
    const cx = width / 2;
    const cy = RADAR_HEIGHT / 2;
    const radius = Math.max(Math.min(width, RADAR_HEIGHT) / 2 - 30, 20);

    const axisPoint = (i: number, r: number) => {
      const a = -Math.PI / 2 + (i / Math.max(axes, 1)) * 2 * Math.PI;
      return { x: cx + r * Math.cos(a), y: cy + r * Math.sin(a) };
    };

    // Concentric polygon gridlines at 25/50/75/100%
    const ringLevels = [0.25, 0.5, 0.75, 1];

    return (
      <Svg width={width} height={RADAR_HEIGHT}>
        {ringLevels.map((lvl) => {
          const pts = Array.from({ length: axes }, (_, i) =>
            axisPoint(i, radius * lvl),
          );
          return (
            <Polygon
              key={`ring-${lvl}`}
              points={pts.map((p) => `${p.x},${p.y}`).join(" ")}
              fill="none"
              stroke={GRID_COLOR}
              strokeOpacity={0.3}
              strokeWidth={1}
            />
          );
        })}
        {props.data.map((_, i) => {
          const p = axisPoint(i, radius);
          return (
            <Line
              // biome-ignore lint/suspicious/noArrayIndexKey: axis index stable
              key={`axis-${i}`}
              x1={cx}
              y1={cy}
              x2={p.x}
              y2={p.y}
              stroke={GRID_COLOR}
              strokeWidth={1}
            />
          );
        })}
        {keys.map((key, ki) => {
          const color = colors[ki % colors.length];
          const pts = props.data.map((row, i) => {
            const r = (toNumber(row[key]) / maxVal) * radius;
            return axisPoint(i, r);
          });
          return (
            <Polygon
              key={key}
              points={pts.map((p) => `${p.x},${p.y}`).join(" ")}
              fill={color}
              fillOpacity={0.2}
              stroke={color}
              strokeOpacity={1}
              strokeWidth={2}
            />
          );
        })}
        {props.data.map((row, i) => {
          const p = axisPoint(i, radius + 12);
          const textAnchor =
            Math.abs(p.x - cx) < 4 ? "middle" : p.x > cx ? "start" : "end";
          return (
            <SvgText
              // biome-ignore lint/suspicious/noArrayIndexKey: label index stable
              key={`label-${i}`}
              x={p.x}
              y={p.y + 3}
              fontSize={AXIS_FONT}
              fill={AXIS_COLOR}
              textAnchor={textAnchor}
            >
              {truncate(String(row[props.angleKey]), 10)}
            </SvgText>
          );
        })}
      </Svg>
    );
  };

  return (
    <ChartShell
      title={props.title}
      description={props.description}
      footer={props.footer}
      height={RADAR_HEIGHT}
      legend={showLegend ? <Legend entries={legendEntries} /> : null}
    >
      {render}
    </ChartShell>
  );
}

// ---------------------------------------------------------------------------
// GaugeChart
// ---------------------------------------------------------------------------

function computeGaugeColor(
  pct: number,
  warning: number,
  danger: number,
): string {
  if (pct >= danger) return "#f87171";
  if (pct >= warning) return "#fbbf24";
  return "#00bbff";
}

export function GaugeChartView(props: z.infer<typeof gaugeChartSchema>) {
  const min = props.min ?? 0;
  const max = props.max ?? 100;
  const clampedValue = Math.min(Math.max(props.value, min), max);
  const range = Math.max(max - min, 1);
  const pct = ((clampedValue - min) / range) * 100;
  const warning = props.thresholds?.warning ?? 60;
  const danger = props.thresholds?.danger ?? 80;
  const color = computeGaugeColor(pct, warning, danger);
  const variant = props.variant ?? "gauge";

  // ---------- variant: "text" ----------
  if (variant === "text") {
    return (
      <Card>
        {props.title ? <SectionTitle>{props.title}</SectionTitle> : null}
        <View
          style={{
            flexDirection: "row",
            alignItems: "flex-end",
            gap: 6,
          }}
        >
          <Text
            className="text-zinc-100"
            style={{
              fontSize: STAT_FONT,
              fontWeight: "600",
              color,
              lineHeight: STAT_FONT + 2,
            }}
          >
            {String(props.value)}
          </Text>
          {props.unit ? (
            <Text
              className="text-zinc-500"
              style={{ fontSize: 14, marginBottom: 4 }}
            >
              {props.unit}
            </Text>
          ) : null}
        </View>
      </Card>
    );
  }

  // ---------- variant: "stacked" ----------
  if (variant === "stacked") {
    const secondValue = props.secondValue ?? 0;
    const secondLabel = props.secondLabel ?? "Secondary";
    const secondColor = CHART_COLORS[1];
    return (
      <Card>
        {props.title ? <SectionTitle>{props.title}</SectionTitle> : null}
        <View
          style={{
            flexDirection: "row",
            alignItems: "center",
            justifyContent: "space-around",
            paddingVertical: 4,
          }}
        >
          <View style={{ alignItems: "center", flex: 1 }}>
            <View
              style={{
                flexDirection: "row",
                alignItems: "flex-end",
                gap: 4,
              }}
            >
              <Text
                style={{
                  fontSize: STAT_FONT,
                  fontWeight: "600",
                  color,
                  lineHeight: STAT_FONT + 2,
                }}
              >
                {String(props.value)}
              </Text>
              {props.unit ? (
                <Text
                  className="text-zinc-500"
                  style={{ fontSize: 14, marginBottom: 2 }}
                >
                  {props.unit}
                </Text>
              ) : null}
            </View>
            <View style={{ marginTop: 4 }}>
              <Text className="text-zinc-500" style={{ fontSize: 12 }}>
                {props.title ?? "Primary"}
              </Text>
            </View>
          </View>
          <View
            className="bg-zinc-700/50"
            style={{
              width: 1,
              height: 40,
            }}
          />
          <View style={{ alignItems: "center", flex: 1 }}>
            <View
              style={{
                flexDirection: "row",
                alignItems: "flex-end",
                gap: 4,
              }}
            >
              <Text
                style={{
                  fontSize: STAT_FONT,
                  fontWeight: "600",
                  color: secondColor,
                  lineHeight: STAT_FONT + 2,
                }}
              >
                {String(secondValue)}
              </Text>
              {props.unit ? (
                <Text
                  className="text-zinc-500"
                  style={{ fontSize: 14, marginBottom: 2 }}
                >
                  {props.unit}
                </Text>
              ) : null}
            </View>
            <View style={{ marginTop: 4 }}>
              <Text className="text-zinc-500" style={{ fontSize: 12 }}>
                {secondLabel}
              </Text>
            </View>
          </View>
        </View>
      </Card>
    );
  }

  // ---------- variant: "gauge" (default) ----------
  const render = (width: number) => {
    const cx = width / 2;
    // Arc thickness 16 per design contract.
    const arcThickness = 16;
    // Leave room for center text & min/max labels at bottom.
    const outerR = Math.max(Math.min(cx - 24, GAUGE_HEIGHT - 60), 40);
    const innerR = outerR - arcThickness;
    const cy = 24 + outerR;
    // Semicircle from 180° (left) to 360° (right): π -> 2π
    const start = Math.PI;
    const end = 2 * Math.PI;
    const valueEnd = start + (pct / 100) * (end - start);

    return (
      <Svg width={width} height={GAUGE_HEIGHT}>
        {/* Background arc */}
        <Path
          d={describeArc(cx, cy, outerR, innerR, start, end)}
          fill={GRID_COLOR}
        />
        {/* Value arc */}
        {pct > 0 ? (
          <Path
            d={describeArc(cx, cy, outerR, innerR, start, valueEnd)}
            fill={color}
          />
        ) : null}
        {/* Center value */}
        <SvgText
          x={cx}
          y={cy - 12}
          fontSize={STAT_FONT}
          fontWeight="600"
          fill={color}
          textAnchor="middle"
        >
          {String(props.value)}
        </SvgText>
        {props.unit ? (
          <SvgText
            x={cx}
            y={cy + 6}
            fontSize={14}
            fill={AXIS_COLOR}
            textAnchor="middle"
          >
            {props.unit}
          </SvgText>
        ) : null}
        {/* Min label */}
        <SvgText
          x={cx - outerR + arcThickness / 2}
          y={cy + 16}
          fontSize={AXIS_FONT}
          fill={AXIS_COLOR}
          textAnchor="middle"
        >
          {formatTick(min)}
        </SvgText>
        {/* Max label */}
        <SvgText
          x={cx + outerR - arcThickness / 2}
          y={cy + 16}
          fontSize={AXIS_FONT}
          fill={AXIS_COLOR}
          textAnchor="middle"
        >
          {formatTick(max)}
        </SvgText>
      </Svg>
    );
  };

  return (
    <ChartShell title={props.title} height={GAUGE_HEIGHT}>
      {render}
    </ChartShell>
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
