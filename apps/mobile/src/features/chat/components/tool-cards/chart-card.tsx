import { useMemo } from "react";
import { ScrollView, View } from "react-native";
import {
  type AnyIcon,
  AppIcon,
  BarChartIcon,
  ChartLineData01Icon,
  ChartRingIcon,
  PieChart01Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import {
  ToolCardInner,
  ToolCardShell,
} from "@/features/chat/tool-data/primitives";

// -- Constants ----------------------------------------------------------------

const PRIMARY = "#00bbff";

const DEFAULT_COLORS = [
  "#60a5fa", // blue
  "#34d399", // green
  "#f9a825", // amber
  "#f87171", // red
  "#a78bfa", // violet
  "#38bdf8", // sky
  "#fb923c", // orange
  "#e879f9", // fuchsia
  "#4ade80", // lime-green
  "#f472b6", // pink
] as const;

function resolveColor(color: string | undefined, index: number): string {
  if (color) return color;
  return DEFAULT_COLORS[index % DEFAULT_COLORS.length];
}

// -- Types --------------------------------------------------------------------

export interface ChartDataPoint {
  label: string;
  value: number;
  color?: string;
}

export interface ChartData {
  type: "bar" | "line" | "pie";
  title?: string;
  data: ChartDataPoint[];
  xLabel?: string;
  yLabel?: string;
}

interface ChartCardProps {
  toolData: ChartData;
}

// -- Helpers ------------------------------------------------------------------

function formatValue(value: number): string {
  if (Math.abs(value) >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (Math.abs(value) >= 1_000) return `${(value / 1_000).toFixed(1)}K`;
  if (!Number.isInteger(value)) return value.toFixed(2);
  return String(value);
}

function resolveChartIcon(type: ChartData["type"]): AnyIcon {
  if (type === "pie") return PieChart01Icon;
  if (type === "line") return ChartLineData01Icon;
  return BarChartIcon;
}

// -- Bar chart ----------------------------------------------------------------

function BarChart({
  data,
  xLabel,
  yLabel,
}: Omit<ChartData, "type" | "title">) {
  const maxValue = useMemo(
    () => Math.max(...data.map((d) => Math.abs(d.value)), 1),
    [data],
  );

  const LABEL_WIDTH = 80;
  const VALUE_WIDTH = 46;
  const BAR_HEIGHT = 16;

  return (
    <View style={{ gap: 4 }}>
      {yLabel && (
        <Text className="text-[10px] text-zinc-500 mb-0.5">{yLabel}</Text>
      )}

      <View style={{ gap: 10 }}>
        {data.map((point, idx) => {
          const fillRatio = Math.abs(point.value) / maxValue;
          const barColor = resolveColor(point.color, idx);

          return (
            <View
              key={`bar-${idx}`}
              className="flex-row items-center"
              style={{ gap: 8 }}
            >
              <Text
                className="text-[11px] text-zinc-400 text-right"
                style={{ width: LABEL_WIDTH }}
                numberOfLines={1}
              >
                {point.label}
              </Text>

              <View
                className="flex-1 bg-zinc-800 overflow-hidden"
                style={{
                  height: BAR_HEIGHT,
                  borderRadius: BAR_HEIGHT / 2,
                }}
              >
                <View
                  style={{
                    width: `${fillRatio * 100}%`,
                    height: BAR_HEIGHT,
                    backgroundColor: barColor,
                    borderRadius: BAR_HEIGHT / 2,
                    minWidth: fillRatio > 0 ? 4 : 0,
                  }}
                />
              </View>

              <Text
                className="text-[11px] font-semibold text-right"
                style={{ color: barColor, width: VALUE_WIDTH }}
              >
                {formatValue(point.value)}
              </Text>
            </View>
          );
        })}
      </View>

      {xLabel && (
        <Text className="text-[10px] text-zinc-500 text-center mt-1">
          {xLabel}
        </Text>
      )}
    </View>
  );
}

// -- Data table (fallback for line/pie) ---------------------------------------

function DataTable({
  data,
  type,
}: {
  data: ChartDataPoint[];
  type: "line" | "pie";
}) {
  const total = useMemo(
    () => data.reduce((sum, d) => sum + d.value, 0),
    [data],
  );
  const showPercent = type === "pie" && total !== 0;

  return (
    <View className="rounded-2xl bg-zinc-900 overflow-hidden">
      {/* Header row */}
      <View className="flex-row bg-zinc-800/50 px-2.5 py-1.5">
        <Text className="text-[10px] font-semibold uppercase tracking-wider text-zinc-400 flex-1">
          Label
        </Text>
        <Text
          className="text-[10px] font-semibold uppercase tracking-wider text-zinc-400 text-right"
          style={{ width: 60 }}
        >
          Value
        </Text>
        {showPercent && (
          <Text
            className="text-[10px] font-semibold uppercase tracking-wider text-zinc-400 text-right"
            style={{ width: 46 }}
          >
            %
          </Text>
        )}
      </View>

      {data.map((point, idx) => {
        const rowColor = resolveColor(point.color, idx);
        const pct = showPercent
          ? ((point.value / total) * 100).toFixed(1)
          : null;

        return (
          <View
            key={`row-${idx}`}
            className={`flex-row items-center px-2.5 py-1.5 ${idx % 2 === 1 ? "bg-zinc-800/50" : ""}`}
          >
            <View
              style={{
                width: 8,
                height: 8,
                borderRadius: 4,
                backgroundColor: rowColor,
                marginRight: 6,
                flexShrink: 0,
              }}
            />
            <Text
              className="text-xs text-zinc-200 flex-1"
              numberOfLines={1}
            >
              {point.label}
            </Text>
            <Text
              className="text-xs font-semibold text-right"
              style={{ color: rowColor, width: 60 }}
            >
              {formatValue(point.value)}
            </Text>
            {showPercent && pct != null && (
              <Text
                className="text-[11px] text-zinc-500 text-right"
                style={{ width: 46 }}
              >
                {pct}%
              </Text>
            )}
          </View>
        );
      })}

      {showPercent && (
        <View className="flex-row items-center px-2.5 py-1.5 bg-zinc-800/50">
          <Text className="text-[11px] font-semibold text-zinc-400 flex-1">
            Total
          </Text>
          <Text
            className="text-xs font-bold text-zinc-200 text-right"
            style={{ width: 60 }}
          >
            {formatValue(total)}
          </Text>
          <Text
            className="text-[11px] text-zinc-500 text-right"
            style={{ width: 46 }}
          >
            100%
          </Text>
        </View>
      )}
    </View>
  );
}

// -- Line chart note ----------------------------------------------------------

function LineChartNote({
  xLabel,
  yLabel,
}: {
  xLabel?: string;
  yLabel?: string;
}) {
  return (
    <ToolCardInner dense className="flex-row items-center mb-2">
      <AppIcon icon={ChartLineData01Icon} size={14} color="#71717a" />
      <Text className="text-[11px] text-zinc-400 flex-1 ml-2">
        Line chart — data shown as table
        {xLabel ? ` · x: ${xLabel}` : ""}
        {yLabel ? ` · y: ${yLabel}` : ""}
      </Text>
    </ToolCardInner>
  );
}

// -- Pie chart legend ---------------------------------------------------------

function PieLegend({ data }: { data: ChartDataPoint[] }) {
  const total = data.reduce((sum, d) => sum + d.value, 0);

  return (
    <View className="rounded-2xl bg-zinc-900 p-3 mb-2" style={{ gap: 4 }}>
      {data.slice(0, 5).map((point, idx) => {
        const color = resolveColor(point.color, idx);
        const pct = total > 0 ? ((point.value / total) * 100).toFixed(1) : "0";
        const barWidth = total > 0 ? (point.value / total) * 100 : 0;

        return (
          <View
            key={`legend-${idx}`}
            className="flex-row items-center"
            style={{ gap: 8 }}
          >
            <View
              style={{
                width: 10,
                height: 10,
                borderRadius: 5,
                backgroundColor: color,
                flexShrink: 0,
              }}
            />
            <Text
              className="text-[11px] text-zinc-400"
              style={{ width: 80 }}
              numberOfLines={1}
            >
              {point.label}
            </Text>
            <View
              className="flex-1 bg-zinc-800 overflow-hidden"
              style={{
                height: 6,
                borderRadius: 3,
              }}
            >
              <View
                style={{
                  width: `${barWidth}%`,
                  height: 6,
                  backgroundColor: color,
                  borderRadius: 3,
                  minWidth: barWidth > 0 ? 3 : 0,
                }}
              />
            </View>
            <Text
              className="text-[10px] text-zinc-500 text-right"
              style={{ width: 36 }}
            >
              {pct}%
            </Text>
          </View>
        );
      })}
      {data.length > 5 && (
        <Text className="text-[10px] text-zinc-500 mt-0.5">
          +{data.length - 5} more — see table below
        </Text>
      )}
    </View>
  );
}

// -- Chart card ---------------------------------------------------------------

export function ChartCard({ toolData }: ChartCardProps) {
  const { type, title, data, xLabel, yLabel } = toolData;

  if (!data || data.length === 0) {
    return (
      <ToolCardShell>
        <View className="flex-row items-center gap-2">
          <View className="w-7 h-7 rounded-xl bg-zinc-700 items-center justify-center">
            <AppIcon icon={ChartRingIcon} size={14} color={PRIMARY} />
          </View>
          <Text className="text-sm font-medium text-zinc-100">
            No chart data available
          </Text>
        </View>
      </ToolCardShell>
    );
  }

  const chartTitle =
    title ??
    (type === "bar"
      ? "Bar Chart"
      : type === "line"
        ? "Line Chart"
        : "Pie Chart");
  const headerIcon = resolveChartIcon(type);

  return (
    <ToolCardShell>
      {/* Header — w-7 h-7 rounded-xl bg-zinc-700 */}
      <View className="flex-row items-center gap-2 mb-3">
        <View className="w-7 h-7 rounded-xl bg-zinc-700 items-center justify-center">
          <AppIcon icon={headerIcon} size={14} color={PRIMARY} />
        </View>
        <Text
          className="text-sm font-medium text-zinc-100 flex-1"
          numberOfLines={1}
        >
          {chartTitle}
        </Text>
        <View className="px-2 py-0.5 rounded-full bg-zinc-700">
          <Text className="text-[11px] font-medium text-zinc-300">
            {data.length} {data.length === 1 ? "item" : "items"}
          </Text>
        </View>
      </View>

      {/* Body */}
      <ScrollView
        style={{ maxHeight: 420 }}
        nestedScrollEnabled
        showsVerticalScrollIndicator={false}
        contentContainerStyle={{ gap: 10 }}
      >
        {type === "bar" && (
          <ToolCardInner>
            <BarChart data={data} xLabel={xLabel} yLabel={yLabel} />
          </ToolCardInner>
        )}

        {type === "line" && (
          <>
            <LineChartNote xLabel={xLabel} yLabel={yLabel} />
            <DataTable data={data} type="line" />
          </>
        )}

        {type === "pie" && (
          <>
            <PieLegend data={data} />
            <DataTable data={data} type="pie" />
          </>
        )}
      </ScrollView>
    </ToolCardShell>
  );
}
