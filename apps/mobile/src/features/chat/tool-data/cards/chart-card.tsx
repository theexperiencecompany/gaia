import { useMemo, useState } from "react";
import { Pressable, ScrollView, View } from "react-native";
import Svg, {
  Circle,
  G,
  Line,
  Path,
  Rect,
  Text as SvgText,
} from "react-native-svg";
import {
  type AnyIcon,
  AppIcon,
  BarChartIcon,
  ChartLineData01Icon,
  ChartRingIcon,
  PieChart01Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { ToolCardInner, ToolCardShell } from "../primitives";

// ---------------------------------------------------------------------------
// Types (matching web ChartDisplay.tsx)
// ---------------------------------------------------------------------------

interface ChartElement {
  label: string;
  value: number;
  group: string;
}

interface ChartData {
  type: string;
  title: string;
  x_label: string;
  y_label: string;
  x_unit?: string | null;
  y_unit?: string | null;
  elements: ChartElement[];
}

export interface ChartDisplayData {
  id?: string;
  url?: string;
  text?: string;
  type?: string;
  title?: string;
  description?: string;
  chart_data?: ChartData;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const PRIMARY = "#00bbff";
const AXIS = "#a1a1aa"; // zinc-400
const GRID = "rgba(255,255,255,0.06)";
const CHART_HEIGHT = 180;
const CHART_WIDTH = 280;
const CHART_PAD = { top: 12, right: 12, bottom: 32, left: 36 };

const BAR_COLORS = [
  "#00bbff",
  "#6366f1",
  "#22c55e",
  "#f59e0b",
  "#ec4899",
  "#8b5cf6",
];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function clamp(val: number, min: number, max: number): number {
  return Math.min(Math.max(val, min), max);
}

function formatAxisValue(v: number): string {
  if (Math.abs(v) >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`;
  if (Math.abs(v) >= 1_000) return `${(v / 1_000).toFixed(1)}K`;
  return v % 1 === 0 ? String(v) : v.toFixed(1);
}

function truncateLabel(label: string, maxLen = 8): string {
  if (label.length <= maxLen) return label;
  return `${label.slice(0, maxLen - 1)}…`;
}

// ---------------------------------------------------------------------------
// Bar Chart
// ---------------------------------------------------------------------------

function BarChartView({ data }: { data: ChartData }) {
  const elements = data.elements.slice(0, 12);
  const plotW = CHART_WIDTH - CHART_PAD.left - CHART_PAD.right;
  const plotH = CHART_HEIGHT - CHART_PAD.top - CHART_PAD.bottom;

  const maxVal = useMemo(
    () => Math.max(...elements.map((e) => e.value), 1),
    [elements],
  );

  const barW = Math.max(6, plotW / elements.length - 4);
  const step = plotW / elements.length;

  const yTicks = useMemo(
    () => [0, 0.25, 0.5, 0.75, 1].map((t) => maxVal * t),
    [maxVal],
  );

  return (
    <Svg width={CHART_WIDTH} height={CHART_HEIGHT}>
      {yTicks.map((tick) => {
        const y = CHART_PAD.top + plotH - (tick / maxVal) * plotH;
        return (
          <G key={`ytick-${tick}`}>
            <Line
              x1={CHART_PAD.left}
              y1={y}
              x2={CHART_PAD.left + plotW}
              y2={y}
              stroke={GRID}
              strokeWidth={1}
            />
            <SvgText
              x={CHART_PAD.left - 4}
              y={y + 4}
              fontSize={8}
              fill={AXIS}
              textAnchor="end"
            >
              {formatAxisValue(tick)}
            </SvgText>
          </G>
        );
      })}

      {elements.map((el, i) => {
        const barH = clamp((el.value / maxVal) * plotH, 0, plotH);
        const x = CHART_PAD.left + i * step + step / 2 - barW / 2;
        const y = CHART_PAD.top + plotH - barH;
        const color = BAR_COLORS[i % BAR_COLORS.length];

        return (
          <G key={`bar-${el.label}-${i}`}>
            <Rect
              x={x}
              y={y}
              width={barW}
              height={barH}
              rx={3}
              fill={color}
              opacity={0.9}
            />
            <SvgText
              x={x + barW / 2}
              y={CHART_PAD.top + plotH + 14}
              fontSize={8}
              fill={AXIS}
              textAnchor="middle"
            >
              {truncateLabel(el.label)}
            </SvgText>
          </G>
        );
      })}

      <Line
        x1={CHART_PAD.left}
        y1={CHART_PAD.top}
        x2={CHART_PAD.left}
        y2={CHART_PAD.top + plotH}
        stroke={GRID}
        strokeWidth={1}
      />
    </Svg>
  );
}

// ---------------------------------------------------------------------------
// Line Chart
// ---------------------------------------------------------------------------

function LineChartView({ data }: { data: ChartData }) {
  const elements = data.elements.slice(0, 20);
  const plotW = CHART_WIDTH - CHART_PAD.left - CHART_PAD.right;
  const plotH = CHART_HEIGHT - CHART_PAD.top - CHART_PAD.bottom;

  const maxVal = useMemo(
    () => Math.max(...elements.map((e) => e.value), 1),
    [elements],
  );
  const minVal = useMemo(
    () => Math.min(...elements.map((e) => e.value), 0),
    [elements],
  );
  const range = Math.max(maxVal - minVal, 1);

  const yTicks = useMemo(
    () => [0, 0.25, 0.5, 0.75, 1].map((t) => minVal + range * t),
    [minVal, range],
  );

  const points = useMemo(
    () =>
      elements.map((el, i) => {
        const x =
          CHART_PAD.left + (i / Math.max(elements.length - 1, 1)) * plotW;
        const y = CHART_PAD.top + plotH - ((el.value - minVal) / range) * plotH;
        return { x, y, el };
      }),
    [elements, plotW, plotH, minVal, range],
  );

  const pathD = useMemo(() => {
    if (points.length === 0) return "";
    return points
      .map((p, i) => `${i === 0 ? "M" : "L"} ${p.x} ${p.y}`)
      .join(" ");
  }, [points]);

  const labelEvery = Math.ceil(elements.length / 6);

  return (
    <Svg width={CHART_WIDTH} height={CHART_HEIGHT}>
      {yTicks.map((tick) => {
        const y = CHART_PAD.top + plotH - ((tick - minVal) / range) * plotH;
        return (
          <G key={`ytick-${tick}`}>
            <Line
              x1={CHART_PAD.left}
              y1={y}
              x2={CHART_PAD.left + plotW}
              y2={y}
              stroke={GRID}
              strokeWidth={1}
            />
            <SvgText
              x={CHART_PAD.left - 4}
              y={y + 4}
              fontSize={8}
              fill={AXIS}
              textAnchor="end"
            >
              {formatAxisValue(tick)}
            </SvgText>
          </G>
        );
      })}

      {pathD.length > 0 && (
        <Path
          d={`${pathD} L ${CHART_PAD.left + plotW} ${CHART_PAD.top + plotH} L ${CHART_PAD.left} ${CHART_PAD.top + plotH} Z`}
          fill={PRIMARY}
          opacity={0.08}
        />
      )}

      {pathD.length > 0 && (
        <Path
          d={pathD}
          stroke={PRIMARY}
          strokeWidth={2}
          fill="none"
          strokeLinejoin="round"
          strokeLinecap="round"
        />
      )}

      {points.map((p) => (
        <Circle
          key={`dot-${p.el.label}`}
          cx={p.x}
          cy={p.y}
          r={3}
          fill={PRIMARY}
        />
      ))}

      {points.map((p, i) => {
        if (i % labelEvery !== 0 && i !== points.length - 1) return null;
        return (
          <SvgText
            key={`xlabel-${p.el.label}`}
            x={p.x}
            y={CHART_PAD.top + plotH + 14}
            fontSize={8}
            fill={AXIS}
            textAnchor="middle"
          >
            {truncateLabel(p.el.label)}
          </SvgText>
        );
      })}

      <Line
        x1={CHART_PAD.left}
        y1={CHART_PAD.top}
        x2={CHART_PAD.left}
        y2={CHART_PAD.top + plotH}
        stroke={GRID}
        strokeWidth={1}
      />
    </Svg>
  );
}

// ---------------------------------------------------------------------------
// Pie Chart
// ---------------------------------------------------------------------------

function PieChartView({ data }: { data: ChartData }) {
  const elements = data.elements.slice(0, 8);
  const total = useMemo(
    () => elements.reduce((sum, e) => sum + Math.abs(e.value), 0),
    [elements],
  );

  const CX = CHART_WIDTH / 2;
  const CY = CHART_HEIGHT / 2 - 8;
  const R = Math.min(CX, CY) - 20;
  const INNER_R = R * 0.5;

  const slices = useMemo(() => {
    let angle = -Math.PI / 2;
    return elements.map((el, i) => {
      const frac = total > 0 ? Math.abs(el.value) / total : 1 / elements.length;
      const startAngle = angle;
      const endAngle = angle + frac * 2 * Math.PI;
      angle = endAngle;
      const midAngle = (startAngle + endAngle) / 2;
      const color = BAR_COLORS[i % BAR_COLORS.length];
      return { el, frac, startAngle, endAngle, midAngle, color };
    });
  }, [elements, total]);

  const describeArc = (
    start: number,
    end: number,
    outerR: number,
    innerR: number,
  ): string => {
    const x1 = CX + outerR * Math.cos(start);
    const y1 = CY + outerR * Math.sin(start);
    const x2 = CX + outerR * Math.cos(end);
    const y2 = CY + outerR * Math.sin(end);
    const ix1 = CX + innerR * Math.cos(end);
    const iy1 = CY + innerR * Math.sin(end);
    const ix2 = CX + innerR * Math.cos(start);
    const iy2 = CY + innerR * Math.sin(start);
    const largeArc = end - start > Math.PI ? 1 : 0;
    return [
      `M ${x1} ${y1}`,
      `A ${outerR} ${outerR} 0 ${largeArc} 1 ${x2} ${y2}`,
      `L ${ix1} ${iy1}`,
      `A ${innerR} ${innerR} 0 ${largeArc} 0 ${ix2} ${iy2}`,
      "Z",
    ].join(" ");
  };

  return (
    <View>
      <Svg width={CHART_WIDTH} height={CHART_HEIGHT - 8}>
        {slices.map((slice) => (
          <Path
            key={`slice-${slice.el.label}`}
            d={describeArc(slice.startAngle, slice.endAngle, R, INNER_R)}
            fill={slice.color}
            opacity={0.9}
          />
        ))}
        <SvgText
          x={CX}
          y={CY - 4}
          fontSize={10}
          fill={AXIS}
          textAnchor="middle"
        >
          {elements.length}
        </SvgText>
        <SvgText
          x={CX}
          y={CY + 10}
          fontSize={8}
          fill={AXIS}
          textAnchor="middle"
        >
          items
        </SvgText>
      </Svg>

      <View className="flex-row flex-wrap gap-x-3 gap-y-1 mt-1 px-2">
        {slices.map((slice) => (
          <View
            key={`legend-${slice.el.label}`}
            className="flex-row items-center gap-1"
          >
            <View
              className="rounded-sm"
              style={{
                width: 8,
                height: 8,
                backgroundColor: slice.color,
              }}
            />
            <Text className="text-[10px] text-zinc-400" numberOfLines={1}>
              {truncateLabel(slice.el.label, 12)}{" "}
              {total > 0 ? `${(slice.frac * 100).toFixed(0)}%` : ""}
            </Text>
          </View>
        ))}
      </View>
    </View>
  );
}

// ---------------------------------------------------------------------------
// Data table fallback — bg-zinc-900 container with alternating rows, no borders
// ---------------------------------------------------------------------------

function DataTable({ data }: { data: ChartData }) {
  const elements = data.elements.slice(0, 10);
  return (
    <View className="rounded-2xl bg-zinc-900 overflow-hidden">
      {/* Header row */}
      <View className="flex-row bg-zinc-800/50 px-3 py-2">
        <Text
          className="text-[11px] font-semibold uppercase tracking-wider text-zinc-400 flex-1"
          numberOfLines={1}
        >
          {data.x_label || "Label"}
        </Text>
        <Text
          className="text-[11px] font-semibold uppercase tracking-wider text-zinc-400 text-right"
          style={{ width: 90 }}
          numberOfLines={1}
        >
          {data.y_label || "Value"}
          {data.y_unit ? ` (${data.y_unit})` : ""}
        </Text>
      </View>

      {elements.map((el, i) => (
        <View
          key={`row-${el.label}-${i}`}
          className={`flex-row px-3 py-2 ${i % 2 === 1 ? "bg-zinc-800/50" : ""}`}
        >
          <Text className="text-xs text-zinc-200 flex-1" numberOfLines={1}>
            {el.label}
          </Text>
          <Text
            className="text-xs font-medium text-right"
            style={{ color: PRIMARY, width: 90 }}
            numberOfLines={1}
          >
            {formatAxisValue(el.value)}
          </Text>
        </View>
      ))}

      {data.elements.length > 10 && (
        <View className="px-3 py-2 bg-zinc-800/50">
          <Text className="text-[11px] text-zinc-500 text-center">
            +{data.elements.length - 10} more rows
          </Text>
        </View>
      )}
    </View>
  );
}

// ---------------------------------------------------------------------------
// Single chart item
// ---------------------------------------------------------------------------

type ChartViewMode = "chart" | "table";

function resolveChartIcon(type: string | undefined): AnyIcon {
  if (type === "pie") return PieChart01Icon;
  if (type === "line") return ChartLineData01Icon;
  if (type === "bar") return BarChartIcon;
  return ChartRingIcon;
}

function ChartItem({
  item,
  isLast,
}: {
  item: ChartDisplayData;
  isLast: boolean;
}) {
  const [viewMode, setViewMode] = useState<ChartViewMode>("chart");
  const cd = item.chart_data;

  const chartTypeIcon = resolveChartIcon(cd?.type);

  const renderChart = () => {
    if (!cd) return null;
    switch (cd.type) {
      case "bar":
        return <BarChartView data={cd} />;
      case "line":
        return <LineChartView data={cd} />;
      case "pie":
        return <PieChartView data={cd} />;
      default:
        return <DataTable data={cd} />;
    }
  };

  const title = item.title ?? cd?.title ?? "Chart";

  return (
    <View className={isLast ? "" : "mb-3"}>
      {/* Item header — w-7 h-7 rounded-xl bg-zinc-700 icon */}
      <View className="flex-row items-center gap-2 mb-2">
        <View className="w-7 h-7 rounded-xl bg-zinc-700 items-center justify-center">
          <AppIcon icon={chartTypeIcon} size={14} color={PRIMARY} />
        </View>
        <Text
          className="text-sm font-medium text-zinc-100 flex-1"
          numberOfLines={1}
        >
          {title}
        </Text>
      </View>

      {/* Toggle chart / table — bg-zinc-700 */}
      {cd && (
        <View className="flex-row gap-1 mb-2 self-start">
          {(["chart", "table"] as ChartViewMode[]).map((mode) => {
            const active = viewMode === mode;
            return (
              <Pressable
                key={mode}
                onPress={() => setViewMode(mode)}
                className={`rounded-full px-2.5 py-1 ${active ? "bg-zinc-700" : "bg-zinc-900"}`}
              >
                <Text
                  className={`text-[11px] font-medium ${active ? "text-zinc-100" : "text-zinc-400"}`}
                >
                  {mode === "chart" ? "Chart" : "Table"}
                </Text>
              </Pressable>
            );
          })}
        </View>
      )}

      {/* Body */}
      {cd && viewMode === "chart" ? (
        <ToolCardInner>
          <ScrollView horizontal showsHorizontalScrollIndicator={false}>
            <View style={{ paddingBottom: 4 }}>{renderChart()}</View>
          </ScrollView>
        </ToolCardInner>
      ) : cd ? (
        <DataTable data={cd} />
      ) : null}

      {!!item.description && (
        <Text
          className="text-[11px] text-zinc-400 mt-1.5"
          numberOfLines={3}
          style={{ lineHeight: 16 }}
        >
          {item.description}
        </Text>
      )}
    </View>
  );
}

// ---------------------------------------------------------------------------
// ChartCard — main export
// ---------------------------------------------------------------------------

export function ChartCard({ data }: { data: unknown }) {
  const charts = (Array.isArray(data) ? data : [data]) as ChartDisplayData[];
  const validCharts = charts.filter(
    (c) => c && (c.chart_data ?? c.title ?? c.text),
  );

  if (validCharts.length === 0) {
    return (
      <ToolCardShell>
        <View className="flex-row items-center gap-2">
          <View className="w-7 h-7 rounded-xl bg-zinc-700 items-center justify-center">
            <AppIcon icon={ChartRingIcon} size={14} color={PRIMARY} />
          </View>
          <Text className="text-sm font-medium text-zinc-100">
            Chart data unavailable
          </Text>
        </View>
      </ToolCardShell>
    );
  }

  const primaryType = validCharts[0]?.chart_data?.type;
  const headerIcon = resolveChartIcon(primaryType);
  const headerTitle =
    validCharts.length === 1 ? "Chart" : `Charts · ${validCharts.length}`;

  return (
    <ToolCardShell>
      {/* Card header — w-7 h-7 rounded-xl bg-zinc-700 */}
      <View className="flex-row items-center gap-2 mb-3">
        <View className="w-7 h-7 rounded-xl bg-zinc-700 items-center justify-center">
          <AppIcon icon={headerIcon} size={14} color={PRIMARY} />
        </View>
        <Text className="text-sm font-medium text-zinc-100">{headerTitle}</Text>
      </View>

      {validCharts.map((item, i) => (
        <ChartItem
          key={item.id ?? `chart-${i}`}
          item={item}
          isLast={i === validCharts.length - 1}
        />
      ))}
    </ToolCardShell>
  );
}
