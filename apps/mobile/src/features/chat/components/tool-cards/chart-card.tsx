import { Card, Chip } from "heroui-native";
import { useMemo } from "react";
import { ScrollView, View } from "react-native";
import {
  AppIcon,
  BarChartIcon,
  ChartLineData01Icon,
  PieChart01Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";

// -- Constants ----------------------------------------------------------------

const COLORS = {
  accentDefault: "#60a5fa",
  subText: "#a1a1aa",
  muted: "#71717a",
  dimmed: "#52525b",
  text: "#e4e4e7",
  barTrack: "#27272a",
  tableBorder: "#27272a",
  tableHeaderBg: "#1e1e2e",
  fallbackBg: "#1e1e2e",
} as const;

// -- Default palette for unlabeled data points --------------------------------

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
  if (Math.abs(value) >= 1_000_000) {
    return `${(value / 1_000_000).toFixed(1)}M`;
  }
  if (Math.abs(value) >= 1_000) {
    return `${(value / 1_000).toFixed(1)}K`;
  }
  if (!Number.isInteger(value)) {
    return value.toFixed(2);
  }
  return String(value);
}

// -- Bar chart ----------------------------------------------------------------

function BarChart({ data, xLabel, yLabel }: Omit<ChartData, "type" | "title">) {
  const maxValue = useMemo(
    () => Math.max(...data.map((d) => Math.abs(d.value)), 1),
    [data],
  );

  const LABEL_WIDTH = 80;
  const VALUE_WIDTH = 46;
  const BAR_HEIGHT = 16;
  const ROW_GAP = 10;

  return (
    <View style={{ gap: 4 }}>
      {yLabel && (
        <Text style={{ fontSize: 10, color: COLORS.muted, marginBottom: 2 }}>
          {yLabel}
        </Text>
      )}

      <View style={{ gap: ROW_GAP }}>
        {data.map((point, idx) => {
          const fillRatio = Math.abs(point.value) / maxValue;
          const barColor = resolveColor(point.color, idx);

          return (
            <View
              key={`bar-${idx}`}
              style={{ flexDirection: "row", alignItems: "center", gap: 8 }}
            >
              {/* Label */}
              <Text
                style={{
                  width: LABEL_WIDTH,
                  fontSize: 11,
                  color: COLORS.subText,
                  textAlign: "right",
                }}
                numberOfLines={1}
              >
                {point.label}
              </Text>

              {/* Bar track */}
              <View
                style={{
                  flex: 1,
                  height: BAR_HEIGHT,
                  backgroundColor: COLORS.barTrack,
                  borderRadius: BAR_HEIGHT / 2,
                  overflow: "hidden",
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

              {/* Value */}
              <Text
                style={{
                  width: VALUE_WIDTH,
                  fontSize: 11,
                  color: barColor,
                  fontWeight: "600",
                  textAlign: "right",
                }}
              >
                {formatValue(point.value)}
              </Text>
            </View>
          );
        })}
      </View>

      {xLabel && (
        <Text
          style={{
            fontSize: 10,
            color: COLORS.muted,
            textAlign: "center",
            marginTop: 4,
          }}
        >
          {xLabel}
        </Text>
      )}
    </View>
  );
}

// -- Data table (fallback for line/pie) ----------------------------------------

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
    <View
      style={{
        borderRadius: 8,
        overflow: "hidden",
        borderWidth: 1,
        borderColor: COLORS.tableBorder,
      }}
    >
      {/* Table header */}
      <View
        style={{
          flexDirection: "row",
          backgroundColor: COLORS.tableHeaderBg,
          paddingHorizontal: 10,
          paddingVertical: 6,
          borderBottomWidth: 1,
          borderBottomColor: COLORS.tableBorder,
        }}
      >
        <Text
          style={{
            flex: 1,
            fontSize: 10,
            color: COLORS.muted,
            fontWeight: "600",
            textTransform: "uppercase",
          }}
        >
          Label
        </Text>
        <Text
          style={{
            fontSize: 10,
            color: COLORS.muted,
            fontWeight: "600",
            textTransform: "uppercase",
            width: 60,
            textAlign: "right",
          }}
        >
          Value
        </Text>
        {showPercent && (
          <Text
            style={{
              fontSize: 10,
              color: COLORS.muted,
              fontWeight: "600",
              textTransform: "uppercase",
              width: 46,
              textAlign: "right",
            }}
          >
            %
          </Text>
        )}
      </View>

      {/* Rows */}
      {data.map((point, idx) => {
        const rowColor = resolveColor(point.color, idx);
        const pct = showPercent
          ? ((point.value / total) * 100).toFixed(1)
          : null;

        return (
          <View
            key={`row-${idx}`}
            style={{
              flexDirection: "row",
              alignItems: "center",
              paddingHorizontal: 10,
              paddingVertical: 7,
              borderBottomWidth: idx < data.length - 1 ? 1 : 0,
              borderBottomColor: COLORS.tableBorder,
            }}
          >
            {/* Color swatch */}
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
              style={{ flex: 1, fontSize: 12, color: COLORS.text }}
              numberOfLines={1}
            >
              {point.label}
            </Text>
            <Text
              style={{
                fontSize: 12,
                color: rowColor,
                fontWeight: "600",
                width: 60,
                textAlign: "right",
              }}
            >
              {formatValue(point.value)}
            </Text>
            {showPercent && pct != null && (
              <Text
                style={{
                  fontSize: 11,
                  color: COLORS.muted,
                  width: 46,
                  textAlign: "right",
                }}
              >
                {pct}%
              </Text>
            )}
          </View>
        );
      })}

      {/* Total row for pie */}
      {showPercent && (
        <View
          style={{
            flexDirection: "row",
            alignItems: "center",
            paddingHorizontal: 10,
            paddingVertical: 7,
            backgroundColor: COLORS.tableHeaderBg,
            borderTopWidth: 1,
            borderTopColor: COLORS.tableBorder,
          }}
        >
          <Text
            style={{
              flex: 1,
              fontSize: 11,
              color: COLORS.muted,
              fontWeight: "600",
            }}
          >
            Total
          </Text>
          <Text
            style={{
              fontSize: 12,
              color: COLORS.subText,
              fontWeight: "700",
              width: 60,
              textAlign: "right",
            }}
          >
            {formatValue(total)}
          </Text>
          <Text
            style={{
              fontSize: 11,
              color: COLORS.dimmed,
              width: 46,
              textAlign: "right",
            }}
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
    <View
      style={{
        backgroundColor: COLORS.fallbackBg,
        borderRadius: 8,
        padding: 10,
        flexDirection: "row",
        alignItems: "center",
        gap: 8,
        marginBottom: 8,
      }}
    >
      <AppIcon icon={ChartLineData01Icon} size={14} color={COLORS.muted} />
      <Text style={{ fontSize: 11, color: COLORS.muted, flex: 1 }}>
        Line chart — data shown as table
        {xLabel ? ` · x: ${xLabel}` : ""}
        {yLabel ? ` · y: ${yLabel}` : ""}
      </Text>
    </View>
  );
}

// -- Pie chart legend ---------------------------------------------------------

function PieLegend({ data }: { data: ChartDataPoint[] }) {
  const total = data.reduce((sum, d) => sum + d.value, 0);

  return (
    <View
      style={{
        backgroundColor: COLORS.fallbackBg,
        borderRadius: 8,
        padding: 10,
        marginBottom: 8,
        gap: 4,
      }}
    >
      {data.slice(0, 5).map((point, idx) => {
        const color = resolveColor(point.color, idx);
        const pct = total > 0 ? ((point.value / total) * 100).toFixed(1) : "0";
        const barWidth = total > 0 ? (point.value / total) * 100 : 0;

        return (
          <View
            key={`legend-${idx}`}
            style={{ flexDirection: "row", alignItems: "center", gap: 8 }}
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
              style={{ fontSize: 11, color: COLORS.subText, width: 80 }}
              numberOfLines={1}
            >
              {point.label}
            </Text>
            <View
              style={{
                flex: 1,
                height: 6,
                backgroundColor: COLORS.barTrack,
                borderRadius: 3,
                overflow: "hidden",
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
              style={{
                fontSize: 10,
                color: COLORS.muted,
                width: 36,
                textAlign: "right",
              }}
            >
              {pct}%
            </Text>
          </View>
        );
      })}
      {data.length > 5 && (
        <Text style={{ fontSize: 10, color: COLORS.dimmed, marginTop: 2 }}>
          +{data.length - 5} more — see table below
        </Text>
      )}
    </View>
  );
}

// -- Chart type icon ----------------------------------------------------------

function ChartTypeIcon({ type }: { type: ChartData["type"] }) {
  if (type === "bar") {
    return (
      <AppIcon icon={BarChartIcon} size={14} color={COLORS.accentDefault} />
    );
  }
  if (type === "line") {
    return (
      <AppIcon
        icon={ChartLineData01Icon}
        size={14}
        color={COLORS.accentDefault}
      />
    );
  }
  return (
    <AppIcon icon={PieChart01Icon} size={14} color={COLORS.accentDefault} />
  );
}

// -- Chart card ---------------------------------------------------------------

export function ChartCard({ toolData }: ChartCardProps) {
  const { type, title, data, xLabel, yLabel } = toolData;

  if (!data || data.length === 0) {
    return (
      <Card variant="secondary" className="mx-4 my-1 rounded-2xl bg-[#171920]">
        <Card.Body className="py-3 px-4 items-center">
          <Text style={{ fontSize: 13, color: COLORS.muted }}>
            No chart data available
          </Text>
        </Card.Body>
      </Card>
    );
  }

  const chartTitle =
    title ??
    (type === "bar"
      ? "Bar Chart"
      : type === "line"
        ? "Line Chart"
        : "Pie Chart");

  return (
    <Card variant="secondary" className="mx-4 my-1 rounded-2xl bg-[#171920]">
      {/* Header */}
      <Card.Header className="flex-row items-center gap-2 px-4 pt-3 pb-2 border-b border-white/8">
        <View
          style={{
            width: 28,
            height: 28,
            borderRadius: 8,
            backgroundColor: "rgba(96,165,250,0.12)",
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          <ChartTypeIcon type={type} />
        </View>
        <Card.Title className="text-sm font-semibold flex-1" numberOfLines={1}>
          {chartTitle}
        </Card.Title>
        <Chip variant="soft" color="default" size="sm">
          <Chip.Label>
            {data.length} {data.length === 1 ? "item" : "items"}
          </Chip.Label>
        </Chip>
      </Card.Header>

      {/* Body */}
      <Card.Body className="p-0">
        <ScrollView
          style={{ maxHeight: 420 }}
          nestedScrollEnabled
          showsVerticalScrollIndicator={false}
          contentContainerStyle={{ padding: 14, gap: 10 }}
        >
          {type === "bar" && (
            <BarChart data={data} xLabel={xLabel} yLabel={yLabel} />
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
      </Card.Body>
    </Card>
  );
}
