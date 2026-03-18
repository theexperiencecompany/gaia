import { Card } from "heroui-native";
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
  AppIcon,
  BarChartIcon,
  ChartLineData01Icon,
  ChartRingIcon,
  PieChart01Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";

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
const _BG_CARD = "#171920";
const MUTED = "#8e8e93";
const GRID = "rgba(255,255,255,0.08)";
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

  const yTicks = useMemo(() => {
    const raw = [0, 0.25, 0.5, 0.75, 1].map((t) => maxVal * t);
    return raw;
  }, [maxVal]);

  return (
    <Svg width={CHART_WIDTH} height={CHART_HEIGHT}>
      {/* Y-axis grid lines + labels */}
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
              fill={MUTED}
              textAnchor="end"
            >
              {formatAxisValue(tick)}
            </SvgText>
          </G>
        );
      })}

      {/* Bars */}
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
              opacity={0.85}
            />
            <SvgText
              x={x + barW / 2}
              y={CHART_PAD.top + plotH + 14}
              fontSize={8}
              fill={MUTED}
              textAnchor="middle"
            >
              {truncateLabel(el.label)}
            </SvgText>
          </G>
        );
      })}

      {/* Y-axis line */}
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

  const yTicks = useMemo(() => {
    return [0, 0.25, 0.5, 0.75, 1].map((t) => minVal + range * t);
  }, [minVal, range]);

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

  const _step = plotW / Math.max(elements.length - 1, 1);
  const labelEvery = Math.ceil(elements.length / 6);

  return (
    <Svg width={CHART_WIDTH} height={CHART_HEIGHT}>
      {/* Grid + Y labels */}
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
              fill={MUTED}
              textAnchor="end"
            >
              {formatAxisValue(tick)}
            </SvgText>
          </G>
        );
      })}

      {/* Area fill */}
      {pathD.length > 0 && (
        <Path
          d={`${pathD} L ${CHART_PAD.left + plotW} ${CHART_PAD.top + plotH} L ${CHART_PAD.left} ${CHART_PAD.top + plotH} Z`}
          fill={PRIMARY}
          opacity={0.08}
        />
      )}

      {/* Line */}
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

      {/* Data points */}
      {points.map((p) => (
        <Circle
          key={`dot-${p.el.label}`}
          cx={p.x}
          cy={p.y}
          r={3}
          fill={PRIMARY}
        />
      ))}

      {/* X labels */}
      {points.map((p, i) => {
        if (i % labelEvery !== 0 && i !== points.length - 1) return null;
        return (
          <SvgText
            key={`xlabel-${p.el.label}`}
            x={p.x}
            y={CHART_PAD.top + plotH + 14}
            fontSize={8}
            fill={MUTED}
            textAnchor="middle"
          >
            {truncateLabel(p.el.label)}
          </SvgText>
        );
      })}

      {/* Y-axis */}
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
        {/* Center label */}
        <SvgText
          x={CX}
          y={CY - 4}
          fontSize={10}
          fill={MUTED}
          textAnchor="middle"
        >
          {elements.length}
        </SvgText>
        <SvgText
          x={CX}
          y={CY + 10}
          fontSize={8}
          fill={MUTED}
          textAnchor="middle"
        >
          items
        </SvgText>
      </Svg>

      {/* Legend */}
      <View className="flex-row flex-wrap gap-x-3 gap-y-1 mt-1 px-2">
        {slices.map((slice) => (
          <View
            key={`legend-${slice.el.label}`}
            className="flex-row items-center gap-1"
          >
            <View
              style={{
                width: 8,
                height: 8,
                borderRadius: 2,
                backgroundColor: slice.color,
              }}
            />
            <Text style={{ color: MUTED, fontSize: 10 }} numberOfLines={1}>
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
// Data table fallback
// ---------------------------------------------------------------------------

function DataTable({ data }: { data: ChartData }) {
  const elements = data.elements.slice(0, 10);
  return (
    <View className="rounded-xl overflow-hidden border border-white/8">
      {/* Header */}
      <View className="flex-row bg-white/5 px-3 py-2">
        <Text style={{ color: MUTED, fontSize: 11, flex: 1 }}>
          {data.x_label || "Label"}
        </Text>
        <Text
          style={{ color: MUTED, fontSize: 11, width: 80, textAlign: "right" }}
        >
          {data.y_label || "Value"}
          {data.y_unit ? ` (${data.y_unit})` : ""}
        </Text>
      </View>
      {elements.map((el, i) => (
        <View
          key={`row-${el.label}-${i}`}
          className="flex-row px-3 py-2 border-t border-white/5"
        >
          <Text
            className="text-foreground flex-1"
            style={{ fontSize: 12 }}
            numberOfLines={1}
          >
            {el.label}
          </Text>
          <Text
            style={{
              color: PRIMARY,
              fontSize: 12,
              width: 80,
              textAlign: "right",
            }}
          >
            {formatAxisValue(el.value)}
          </Text>
        </View>
      ))}
      {data.elements.length > 10 && (
        <View className="px-3 py-2 border-t border-white/5">
          <Text style={{ color: MUTED, fontSize: 11, textAlign: "center" }}>
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

function ChartItem({ item }: { item: ChartDisplayData }) {
  const [viewMode, setViewMode] = useState<ChartViewMode>("chart");
  const cd = item.chart_data;

  const chartTypeIcon =
    cd?.type === "pie"
      ? PieChart01Icon
      : cd?.type === "line"
        ? ChartLineData01Icon
        : BarChartIcon;

  const chartTypeLabel =
    cd?.type === "bar"
      ? "Bar"
      : cd?.type === "line"
        ? "Line"
        : cd?.type === "pie"
          ? "Pie"
          : "Chart";

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

  return (
    <View className="mb-3">
      {/* Item header */}
      <View className="flex-row items-center gap-2 mb-2">
        <View className="w-5 h-5 rounded-md bg-primary/15 items-center justify-center">
          <AppIcon
            icon={chartTypeIcon}
            size={12}
            color={PRIMARY}
            strokeWidth={2}
          />
        </View>
        <Text
          className="text-xs font-medium text-foreground flex-1"
          numberOfLines={1}
        >
          {item.title ?? cd?.title ?? "Chart"}
        </Text>
        <Text style={{ color: MUTED, fontSize: 10 }}>{chartTypeLabel}</Text>
      </View>

      {/* Toggle chart / table */}
      {cd && (
        <View className="flex-row gap-1 mb-2 self-start">
          {(["chart", "table"] as ChartViewMode[]).map((mode) => (
            <Pressable
              key={mode}
              onPress={() => setViewMode(mode)}
              className={`rounded-full px-2.5 py-1 ${viewMode === mode ? "bg-primary/20" : "bg-white/5"}`}
            >
              <Text
                style={{
                  fontSize: 11,
                  fontWeight: "500",
                  color: viewMode === mode ? PRIMARY : MUTED,
                }}
              >
                {mode.charAt(0).toUpperCase() + mode.slice(1)}
              </Text>
            </Pressable>
          ))}
        </View>
      )}

      {/* Chart or table */}
      {cd && viewMode === "chart" ? (
        <ScrollView horizontal showsHorizontalScrollIndicator={false}>
          <View style={{ paddingBottom: 4 }}>{renderChart()}</View>
        </ScrollView>
      ) : cd ? (
        <DataTable data={cd} />
      ) : null}

      {/* Description */}
      {!!item.description && (
        <Text
          style={{ color: MUTED, fontSize: 11, marginTop: 6, lineHeight: 16 }}
          numberOfLines={3}
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
      <Card variant="secondary" className="mx-4 my-2 rounded-2xl bg-[#171920]">
        <Card.Body className="py-3 px-4">
          <View className="flex-row items-center gap-2">
            <View className="w-5 h-5 rounded-md bg-primary/15 items-center justify-center">
              <AppIcon
                icon={ChartRingIcon}
                size={12}
                color={PRIMARY}
                strokeWidth={2}
              />
            </View>
            <Text className="text-xs text-muted">Chart data unavailable</Text>
          </View>
        </Card.Body>
      </Card>
    );
  }

  return (
    <Card variant="secondary" className="mx-4 my-2 rounded-2xl bg-[#171920]">
      <Card.Body className="py-3 px-4">
        {/* Card header */}
        <View className="flex-row items-center gap-2 mb-3">
          <View className="w-5 h-5 rounded-md bg-primary/15 items-center justify-center">
            <AppIcon
              icon={ChartRingIcon}
              size={12}
              color={PRIMARY}
              strokeWidth={2}
            />
          </View>
          <Text className="text-xs font-medium text-muted">
            {validCharts.length === 1
              ? "Chart"
              : `Charts · ${validCharts.length}`}
          </Text>
        </View>

        {validCharts.map((item, i) => (
          <ChartItem key={item.id ?? `chart-${i}`} item={item} />
        ))}
      </Card.Body>
    </Card>
  );
}
