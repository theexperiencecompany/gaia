import { useRouter } from "expo-router";
import { useEffect, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  Pressable,
  ScrollView,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import {
  AppIcon,
  ArrowLeft01Icon,
  ChartLineData02Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import type {
  UsageHistoryEntry,
  UsageSummary,
} from "@/features/settings/api/settings-api";
import { settingsApi } from "@/features/settings/api/settings-api";
import { useResponsive } from "@/lib/responsive";

// ─── Color tokens ─────────────────────────────────────────────────────────────
const C = {
  bg: "#131416",
  sectionBg: "#171920",
  divider: "rgba(255,255,255,0.06)",
  text: "#ffffff",
  textMuted: "#8e8e93",
  textSubtle: "#5a5a5e",
  primary: "#00bbff",
  primaryBg: "rgba(0,187,255,0.15)",
  danger: "#ef4444",
  warning: "#f59e0b",
  success: "#22c55e",
};

// ─── Helpers ─────────────────────────────────────────────────────────────────

function getBarColor(pct: number): string {
  if (pct >= 90) return C.danger;
  if (pct >= 70) return C.warning;
  return C.primary;
}

function formatNumber(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return n.toString();
}

function formatDate(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

// ─── Period toggle ────────────────────────────────────────────────────────────

type PeriodKey = "day" | "month";

interface PeriodToggleProps {
  value: PeriodKey;
  onChange: (key: PeriodKey) => void;
}

function PeriodToggle({ value, onChange }: PeriodToggleProps) {
  const { spacing, fontSize } = useResponsive();
  return (
    <View style={{ flexDirection: "row", gap: spacing.sm }}>
      {(["day", "month"] as PeriodKey[]).map((key) => {
        const isActive = value === key;
        return (
          <Pressable
            key={key}
            onPress={() => onChange(key)}
            style={{
              borderRadius: 999,
              paddingHorizontal: spacing.md,
              paddingVertical: 5,
              backgroundColor: isActive
                ? C.primaryBg
                : "rgba(255,255,255,0.07)",
            }}
          >
            <Text
              style={{
                fontSize: fontSize.xs,
                color: isActive ? C.primary : "#c5cad2",
                fontWeight: isActive ? "600" : "400",
              }}
            >
              {key === "day" ? "Daily" : "Monthly"}
            </Text>
          </Pressable>
        );
      })}
    </View>
  );
}

// ─── Summary card ─────────────────────────────────────────────────────────────

interface SummaryCardProps {
  summary: UsageSummary;
  period: PeriodKey;
}

function SummaryCard({ summary, period }: SummaryCardProps) {
  const { spacing, fontSize } = useResponsive();
  const isPro = summary.plan_type !== "free";

  // Aggregate totals across features for the selected period
  let _totalUsed = 0;
  let totalLimit = 0;
  let apiCalls = 0;

  for (const feature of Object.values(summary.features)) {
    const p = feature.periods[period];
    if (p) {
      _totalUsed += p.used;
      totalLimit += p.limit;
      apiCalls += p.used;
    }
  }

  // Token totals
  let totalTokens = 0;
  let tokenLimit = 0;
  for (const tok of Object.values(summary.token_usage)) {
    const p = tok.periods[period];
    if (p) {
      totalTokens += p.total_tokens;
      tokenLimit += p.limit;
    }
  }

  const stats: Array<{ label: string; value: string; sub?: string }> = [
    {
      label: "API Calls",
      value: formatNumber(apiCalls),
      sub: `of ${formatNumber(totalLimit)} limit`,
    },
    {
      label: "Tokens Used",
      value: formatNumber(totalTokens),
      sub: tokenLimit > 0 ? `of ${formatNumber(tokenLimit)} limit` : undefined,
    },
    {
      label: "Plan",
      value: isPro ? "Pro" : "Free",
      sub: undefined,
    },
  ];

  return (
    <View
      style={{
        backgroundColor: C.sectionBg,
        borderRadius: 16,
        padding: spacing.md,
        gap: spacing.md,
      }}
    >
      <View
        style={{
          flexDirection: "row",
          alignItems: "center",
          justifyContent: "space-between",
        }}
      >
        <Text
          style={{
            fontSize: fontSize.xs,
            fontWeight: "600",
            textTransform: "uppercase",
            letterSpacing: 0.8,
            color: C.textMuted,
          }}
        >
          {period === "day" ? "Today" : "This Month"}
        </Text>
        <View
          style={{
            backgroundColor: isPro ? C.primaryBg : "rgba(255,255,255,0.06)",
            borderRadius: 999,
            paddingHorizontal: 10,
            paddingVertical: 3,
          }}
        >
          <Text
            style={{
              fontSize: fontSize.xs,
              fontWeight: "700",
              color: isPro ? C.primary : C.textMuted,
            }}
          >
            {isPro ? "PRO" : "FREE"}
          </Text>
        </View>
      </View>

      <View style={{ flexDirection: "row", gap: spacing.sm }}>
        {stats.map(({ label, value, sub }) => (
          <View
            key={label}
            style={{
              flex: 1,
              backgroundColor: "rgba(255,255,255,0.04)",
              borderRadius: 12,
              padding: spacing.sm + 2,
              gap: 2,
            }}
          >
            <Text
              style={{
                fontSize: fontSize.lg,
                fontWeight: "700",
                color: C.text,
              }}
            >
              {value}
            </Text>
            <Text style={{ fontSize: fontSize.xs - 1, color: C.textMuted }}>
              {label}
            </Text>
            {sub ? (
              <Text style={{ fontSize: fontSize.xs - 2, color: C.textSubtle }}>
                {sub}
              </Text>
            ) : null}
          </View>
        ))}
      </View>
    </View>
  );
}

// ─── Feature usage bars ───────────────────────────────────────────────────────

interface FeatureBarsProps {
  summary: UsageSummary;
  period: PeriodKey;
}

function FeatureBars({ summary, period }: FeatureBarsProps) {
  const { spacing, fontSize } = useResponsive();
  const entries = Object.entries(summary.features).filter(
    ([, f]) => f.periods[period],
  );

  if (entries.length === 0) {
    return (
      <View
        style={{
          backgroundColor: C.sectionBg,
          borderRadius: 16,
          padding: spacing.lg,
          alignItems: "center",
          gap: spacing.sm,
        }}
      >
        <AppIcon icon={ChartLineData02Icon} size={28} color={C.textSubtle} />
        <Text style={{ fontSize: fontSize.sm, color: C.textMuted }}>
          No usage data for this period.
        </Text>
      </View>
    );
  }

  return (
    <View
      style={{
        backgroundColor: C.sectionBg,
        borderRadius: 16,
        overflow: "hidden",
      }}
    >
      <View
        style={{
          paddingHorizontal: spacing.md,
          paddingTop: spacing.md,
          paddingBottom: spacing.xs,
        }}
      >
        <Text
          style={{
            fontSize: fontSize.xs,
            fontWeight: "600",
            textTransform: "uppercase",
            letterSpacing: 0.8,
            color: C.textMuted,
          }}
        >
          Feature Breakdown
        </Text>
      </View>

      {entries.map(([key, feature], index) => {
        const p = feature.periods[period];
        if (!p) return null;
        const pct = Math.min(p.percentage, 100);
        return (
          <View key={key}>
            {index > 0 && (
              <View
                style={{
                  height: 1,
                  backgroundColor: C.divider,
                  marginHorizontal: 16,
                }}
              />
            )}
            <View style={{ padding: spacing.md, gap: spacing.xs }}>
              <View
                style={{
                  flexDirection: "row",
                  justifyContent: "space-between",
                }}
              >
                <Text style={{ fontSize: fontSize.sm, color: C.text }}>
                  {feature.title}
                </Text>
                <Text style={{ fontSize: fontSize.xs, color: C.textMuted }}>
                  {p.used.toLocaleString()} / {p.limit.toLocaleString()}
                </Text>
              </View>
              <View
                style={{
                  height: 5,
                  borderRadius: 3,
                  backgroundColor: "rgba(255,255,255,0.08)",
                  overflow: "hidden",
                }}
              >
                <View
                  style={{
                    height: "100%",
                    width: `${pct}%`,
                    borderRadius: 3,
                    backgroundColor: getBarColor(pct),
                  }}
                />
              </View>
              {p.reset_time ? (
                <Text
                  style={{ fontSize: fontSize.xs - 1, color: C.textSubtle }}
                >
                  Resets {formatDate(p.reset_time)}
                </Text>
              ) : null}
            </View>
          </View>
        );
      })}
    </View>
  );
}

// ─── Token model breakdown ────────────────────────────────────────────────────

interface ModelBreakdownProps {
  summary: UsageSummary;
  period: PeriodKey;
}

function ModelBreakdown({ summary, period }: ModelBreakdownProps) {
  const { spacing, fontSize } = useResponsive();
  const entries = Object.entries(summary.token_usage).filter(
    ([, t]) => t.periods[period],
  );

  if (entries.length === 0) return null;

  return (
    <View>
      <Text
        style={{
          fontSize: fontSize.xs,
          fontWeight: "600",
          textTransform: "uppercase",
          letterSpacing: 0.8,
          color: C.textMuted,
          marginBottom: spacing.xs,
          paddingHorizontal: 4,
        }}
      >
        Token Usage by Model
      </Text>
      <View
        style={{
          backgroundColor: C.sectionBg,
          borderRadius: 16,
          overflow: "hidden",
        }}
      >
        {entries.map(([key, tok], index) => {
          const p = tok.periods[period];
          if (!p) return null;
          const pct =
            p.limit > 0 ? Math.min((p.total_tokens / p.limit) * 100, 100) : 0;
          return (
            <View key={key}>
              {index > 0 && (
                <View
                  style={{
                    height: 1,
                    backgroundColor: C.divider,
                    marginHorizontal: 16,
                  }}
                />
              )}
              <View style={{ padding: spacing.md, gap: spacing.sm }}>
                <View
                  style={{
                    flexDirection: "row",
                    justifyContent: "space-between",
                    alignItems: "flex-start",
                  }}
                >
                  <View style={{ flex: 1 }}>
                    <Text
                      style={{
                        fontSize: fontSize.sm,
                        fontWeight: "500",
                        color: C.text,
                      }}
                    >
                      {tok.title}
                    </Text>
                    <Text
                      style={{
                        fontSize: fontSize.xs,
                        color: C.textMuted,
                        marginTop: 2,
                      }}
                    >
                      In: {formatNumber(p.input_tokens)} · Out:{" "}
                      {formatNumber(p.output_tokens)}
                    </Text>
                  </View>
                  <Text style={{ fontSize: fontSize.xs, color: C.textMuted }}>
                    {formatNumber(p.total_tokens)}{" "}
                    {p.limit > 0 ? `/ ${formatNumber(p.limit)}` : "tokens"}
                  </Text>
                </View>
                {p.limit > 0 ? (
                  <View
                    style={{
                      height: 4,
                      borderRadius: 2,
                      backgroundColor: "rgba(255,255,255,0.08)",
                      overflow: "hidden",
                    }}
                  >
                    <View
                      style={{
                        height: "100%",
                        width: `${pct}%`,
                        borderRadius: 2,
                        backgroundColor: getBarColor(pct),
                      }}
                    />
                  </View>
                ) : null}
              </View>
            </View>
          );
        })}
      </View>
    </View>
  );
}

// ─── 7-day bar chart ──────────────────────────────────────────────────────────

interface DailyChartProps {
  history: UsageHistoryEntry[];
}

function DailyChart({ history }: DailyChartProps) {
  const { spacing, fontSize } = useResponsive();

  // Compute per-day total usage across all features (sum of "used" values)
  const bars = history
    .slice()
    .reverse()
    .map((entry) => {
      let total = 0;
      for (const feature of Object.values(entry.features)) {
        const p = feature.periods.day;
        if (p) total += p.used;
      }
      return { date: entry.date, total };
    });

  const maxVal = Math.max(...bars.map((b) => b.total), 1);
  const BAR_MAX_HEIGHT = 72;

  return (
    <View>
      <Text
        style={{
          fontSize: fontSize.xs,
          fontWeight: "600",
          textTransform: "uppercase",
          letterSpacing: 0.8,
          color: C.textMuted,
          marginBottom: spacing.xs,
          paddingHorizontal: 4,
        }}
      >
        Last 7 Days
      </Text>
      <View
        style={{
          backgroundColor: C.sectionBg,
          borderRadius: 16,
          padding: spacing.md,
        }}
      >
        <View
          style={{
            flexDirection: "row",
            alignItems: "flex-end",
            justifyContent: "space-between",
            height: BAR_MAX_HEIGHT + 32,
          }}
        >
          {bars.map(({ date, total }) => {
            const barH = maxVal > 0 ? (total / maxVal) * BAR_MAX_HEIGHT : 0;
            const label = formatDate(date);
            return (
              <View
                key={date}
                style={{
                  flex: 1,
                  alignItems: "center",
                  gap: spacing.xs,
                  paddingHorizontal: 3,
                }}
              >
                {total > 0 ? (
                  <Text
                    style={{
                      fontSize: fontSize.xs - 2,
                      color: C.textMuted,
                    }}
                    numberOfLines={1}
                  >
                    {formatNumber(total)}
                  </Text>
                ) : (
                  <Text
                    style={{ fontSize: fontSize.xs - 2, color: "transparent" }}
                  >
                    0
                  </Text>
                )}
                <View
                  style={{
                    width: "100%",
                    height: Math.max(barH, total > 0 ? 4 : 2),
                    borderRadius: 4,
                    backgroundColor:
                      total > 0 ? C.primary : "rgba(255,255,255,0.06)",
                  }}
                />
                <Text
                  style={{
                    fontSize: fontSize.xs - 2,
                    color: C.textSubtle,
                  }}
                  numberOfLines={1}
                >
                  {label}
                </Text>
              </View>
            );
          })}
        </View>
      </View>
    </View>
  );
}

// ─── History list ─────────────────────────────────────────────────────────────

interface HistoryListProps {
  history: UsageHistoryEntry[];
}

function HistoryList({ history }: HistoryListProps) {
  const { spacing, fontSize } = useResponsive();

  const recent = history.slice(0, 10);

  if (recent.length === 0) return null;

  return (
    <View>
      <Text
        style={{
          fontSize: fontSize.xs,
          fontWeight: "600",
          textTransform: "uppercase",
          letterSpacing: 0.8,
          color: C.textMuted,
          marginBottom: spacing.xs,
          paddingHorizontal: 4,
        }}
      >
        Recent Activity
      </Text>
      <View
        style={{
          backgroundColor: C.sectionBg,
          borderRadius: 16,
          overflow: "hidden",
        }}
      >
        {recent.map((entry, index) => {
          // Find the first feature with day period data to show as representative
          const firstFeature = Object.values(entry.features)[0];
          const dayPeriod = firstFeature?.periods.day;
          const totalUsed = Object.values(entry.features).reduce((acc, f) => {
            return acc + (f.periods.day?.used ?? 0);
          }, 0);

          return (
            <View key={entry.date}>
              {index > 0 && (
                <View
                  style={{
                    height: 1,
                    backgroundColor: C.divider,
                    marginHorizontal: 16,
                  }}
                />
              )}
              <View
                style={{
                  flexDirection: "row",
                  alignItems: "center",
                  paddingHorizontal: spacing.md,
                  paddingVertical: 13,
                }}
              >
                <View style={{ flex: 1 }}>
                  <Text style={{ fontSize: fontSize.sm, color: C.text }}>
                    {formatDate(entry.date)}
                  </Text>
                  <Text
                    style={{
                      fontSize: fontSize.xs,
                      color: C.textMuted,
                      marginTop: 2,
                    }}
                  >
                    {entry.plan_type.charAt(0).toUpperCase() +
                      entry.plan_type.slice(1)}{" "}
                    plan
                  </Text>
                </View>
                <View style={{ alignItems: "flex-end" }}>
                  <Text
                    style={{
                      fontSize: fontSize.sm,
                      fontWeight: "600",
                      color: C.text,
                    }}
                  >
                    {formatNumber(totalUsed)}
                  </Text>
                  <Text
                    style={{
                      fontSize: fontSize.xs,
                      color: C.textMuted,
                      marginTop: 2,
                    }}
                  >
                    {dayPeriod
                      ? `${Object.keys(entry.features).length} feature${Object.keys(entry.features).length !== 1 ? "s" : ""}`
                      : "—"}
                  </Text>
                </View>
              </View>
            </View>
          );
        })}
      </View>
    </View>
  );
}

// ─── Main screen ──────────────────────────────────────────────────────────────

export default function UsageScreen() {
  const router = useRouter();
  const { spacing, fontSize } = useResponsive();
  const insets = useSafeAreaInsets();

  const [period, setPeriod] = useState<PeriodKey>("day");
  const [summary, setSummary] = useState<UsageSummary | null>(null);
  const [history, setHistory] = useState<UsageHistoryEntry[]>([]);
  const [isLoadingSummary, setIsLoadingSummary] = useState(true);
  const [isLoadingHistory, setIsLoadingHistory] = useState(true);

  useEffect(() => {
    let cancelled = false;

    setIsLoadingSummary(true);
    settingsApi
      .getUsageSummary()
      .then((data) => {
        if (!cancelled) setSummary(data);
      })
      .catch(() => {
        if (!cancelled) Alert.alert("Error", "Failed to load usage summary.");
      })
      .finally(() => {
        if (!cancelled) setIsLoadingSummary(false);
      });

    setIsLoadingHistory(true);
    settingsApi
      .getUsageHistory(7)
      .then((data) => {
        if (!cancelled) setHistory(data);
      })
      .catch(() => {
        // History may not be available in all environments — fail silently
        if (!cancelled) setHistory([]);
      })
      .finally(() => {
        if (!cancelled) setIsLoadingHistory(false);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  const isLoading = isLoadingSummary;

  return (
    <View style={{ flex: 1, backgroundColor: C.bg }}>
      {/* Header */}
      <View
        style={{
          paddingTop: insets.top + spacing.sm,
          paddingHorizontal: spacing.md,
          paddingBottom: spacing.md,
          borderBottomWidth: 1,
          borderBottomColor: C.divider,
          flexDirection: "row",
          alignItems: "center",
        }}
      >
        <Pressable
          onPress={() => router.back()}
          style={{
            width: 36,
            height: 36,
            borderRadius: 999,
            alignItems: "center",
            justifyContent: "center",
            backgroundColor: "rgba(255,255,255,0.05)",
          }}
        >
          <AppIcon icon={ArrowLeft01Icon} size={18} color={C.text} />
        </Pressable>
        <Text
          style={{
            marginLeft: spacing.md,
            fontSize: fontSize.base,
            fontWeight: "600",
            color: C.text,
            flex: 1,
          }}
        >
          Usage & Billing
        </Text>
      </View>

      {isLoading ? (
        <View
          style={{ flex: 1, alignItems: "center", justifyContent: "center" }}
        >
          <ActivityIndicator color={C.primary} />
        </View>
      ) : !summary ? (
        <View
          style={{
            flex: 1,
            alignItems: "center",
            justifyContent: "center",
            padding: spacing.lg,
            gap: spacing.md,
          }}
        >
          <AppIcon icon={ChartLineData02Icon} size={40} color={C.textSubtle} />
          <Text
            style={{
              fontSize: fontSize.base,
              fontWeight: "500",
              color: C.text,
            }}
          >
            No usage data
          </Text>
          <Text
            style={{
              fontSize: fontSize.sm,
              color: C.textMuted,
              textAlign: "center",
            }}
          >
            Usage data will appear here once you start using GAIA.
          </Text>
        </View>
      ) : (
        <ScrollView
          showsVerticalScrollIndicator={false}
          contentContainerStyle={{
            paddingTop: spacing.lg,
            paddingHorizontal: spacing.md,
            paddingBottom: insets.bottom + spacing.lg,
            gap: spacing.lg,
          }}
        >
          {/* Period toggle */}
          <View
            style={{
              flexDirection: "row",
              alignItems: "center",
              justifyContent: "space-between",
            }}
          >
            <Text
              style={{
                fontSize: fontSize.xs,
                fontWeight: "600",
                textTransform: "uppercase",
                letterSpacing: 0.8,
                color: C.textMuted,
              }}
            >
              Overview
            </Text>
            <PeriodToggle value={period} onChange={setPeriod} />
          </View>

          {/* Summary card */}
          <SummaryCard summary={summary} period={period} />

          {/* Feature usage bars */}
          <FeatureBars summary={summary} period={period} />

          {/* Token / model breakdown */}
          <ModelBreakdown summary={summary} period={period} />

          {/* 7-day chart */}
          {isLoadingHistory ? (
            <View style={{ alignItems: "center", paddingVertical: spacing.md }}>
              <ActivityIndicator color={C.primary} size="small" />
            </View>
          ) : history.length > 0 ? (
            <>
              <DailyChart history={history} />
              <HistoryList history={history} />
            </>
          ) : null}
        </ScrollView>
      )}
    </View>
  );
}
