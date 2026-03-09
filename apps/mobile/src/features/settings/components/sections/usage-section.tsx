import { useEffect, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  Pressable,
  ScrollView,
  View,
} from "react-native";
import { Text } from "@/components/ui/text";
import type {
  UsagePeriod,
  UsageSummary,
} from "@/features/settings/api/settings-api";
import { settingsApi } from "@/features/settings/api/settings-api";
import { useResponsive } from "@/lib/responsive";

type PeriodKey = "day" | "month";

interface UsageBarProps {
  title: string;
  period: UsagePeriod | undefined;
}

function UsageBar({ title, period }: UsageBarProps) {
  const { spacing, fontSize } = useResponsive();
  if (!period) return null;

  const pct = Math.min(period.percentage, 100);
  const barColor = pct >= 90 ? "#ef4444" : pct >= 70 ? "#f59e0b" : "#16c1ff";

  return (
    <View style={{ gap: spacing.xs }}>
      <View style={{ flexDirection: "row", justifyContent: "space-between" }}>
        <Text style={{ fontSize: fontSize.sm }}>{title}</Text>
        <Text style={{ fontSize: fontSize.xs, color: "#8e8e93" }}>
          {period.used} / {period.limit}
        </Text>
      </View>

      {/* Track */}
      <View
        style={{
          height: 6,
          borderRadius: 3,
          backgroundColor: "rgba(255,255,255,0.1)",
          overflow: "hidden",
        }}
      >
        <View
          style={{
            height: "100%",
            width: `${pct}%`,
            borderRadius: 3,
            backgroundColor: barColor,
          }}
        />
      </View>

      <Text style={{ fontSize: fontSize.xs - 1, color: "#5a5a5e" }}>
        {period.remaining} remaining
        {period.reset_time
          ? ` · resets ${new Date(period.reset_time).toLocaleDateString()}`
          : ""}
      </Text>
    </View>
  );
}

export function UsageSection() {
  const { spacing, fontSize } = useResponsive();
  const [summary, setSummary] = useState<UsageSummary | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [periodKey, setPeriodKey] = useState<PeriodKey>("day");

  useEffect(() => {
    let cancelled = false;
    setIsLoading(true);
    settingsApi
      .getUsageSummary()
      .then((data) => {
        if (!cancelled) setSummary(data);
      })
      .catch(() => {
        if (!cancelled) Alert.alert("Error", "Failed to load usage data.");
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (isLoading) {
    return (
      <View style={{ flex: 1, alignItems: "center", justifyContent: "center" }}>
        <ActivityIndicator color="#16c1ff" />
      </View>
    );
  }

  if (!summary) {
    return (
      <View
        style={{
          flex: 1,
          alignItems: "center",
          justifyContent: "center",
          padding: spacing.lg,
        }}
      >
        <Text style={{ color: "#8e8e93", textAlign: "center" }}>
          No usage data available.
        </Text>
      </View>
    );
  }

  const featureEntries = Object.entries(summary.features);
  const isPro = summary.plan_type !== "free";

  return (
    <ScrollView
      showsVerticalScrollIndicator={false}
      contentContainerStyle={{
        padding: spacing.md,
        gap: spacing.lg,
        paddingBottom: 40,
      }}
    >
      {/* Plan badge */}
      <View
        style={{
          flexDirection: "row",
          alignItems: "center",
          justifyContent: "space-between",
          backgroundColor: "#1c1c1e",
          borderRadius: 12,
          padding: spacing.md,
        }}
      >
        <View>
          <Text
            style={{
              fontSize: fontSize.xs,
              color: "#8e8e93",
              textTransform: "uppercase",
              letterSpacing: 1,
            }}
          >
            Plan
          </Text>
          <Text
            style={{ fontSize: fontSize.base, fontWeight: "600", marginTop: 2 }}
          >
            {isPro ? "Pro" : "Free"}
          </Text>
        </View>
        {!isPro && (
          <Pressable
            style={{
              backgroundColor: "#16c1ff",
              borderRadius: 8,
              paddingHorizontal: spacing.md,
              paddingVertical: spacing.xs,
            }}
          >
            <Text
              style={{
                color: "#000",
                fontWeight: "600",
                fontSize: fontSize.xs,
              }}
            >
              Upgrade
            </Text>
          </Pressable>
        )}
      </View>

      {/* Period toggle */}
      <View style={{ flexDirection: "row", gap: spacing.sm }}>
        {(["day", "month"] as PeriodKey[]).map((key) => {
          const isActive = periodKey === key;
          return (
            <Pressable
              key={key}
              onPress={() => setPeriodKey(key)}
              style={{
                borderRadius: 999,
                paddingHorizontal: spacing.md,
                paddingVertical: spacing.xs,
                backgroundColor: isActive
                  ? "rgba(22,193,255,0.2)"
                  : "rgba(255,255,255,0.07)",
              }}
            >
              <Text
                style={{
                  fontSize: fontSize.xs,
                  color: isActive ? "#9fe6ff" : "#c5cad2",
                  fontWeight: isActive ? "600" : "400",
                }}
              >
                {key === "day" ? "Daily" : "Monthly"}
              </Text>
            </Pressable>
          );
        })}
      </View>

      {/* Feature usage bars */}
      <View
        style={{
          backgroundColor: "#1c1c1e",
          borderRadius: 12,
          padding: spacing.md,
          gap: spacing.lg,
        }}
      >
        {featureEntries.length === 0 ? (
          <Text style={{ color: "#8e8e93", fontSize: fontSize.sm }}>
            No feature usage data.
          </Text>
        ) : (
          featureEntries.map(([key, feature]) => (
            <UsageBar
              key={key}
              title={feature.title}
              period={feature.periods[periodKey]}
            />
          ))
        )}
      </View>

      {/* Token usage */}
      {Object.entries(summary.token_usage).length > 0 && (
        <View style={{ gap: spacing.sm }}>
          <Text
            style={{
              fontSize: fontSize.xs,
              color: "#8e8e93",
              textTransform: "uppercase",
              letterSpacing: 1,
            }}
          >
            Token Usage
          </Text>
          <View
            style={{
              backgroundColor: "#1c1c1e",
              borderRadius: 12,
              padding: spacing.md,
              gap: spacing.md,
            }}
          >
            {Object.entries(summary.token_usage).map(([key, tok]) => {
              const period = tok.periods[periodKey];
              if (!period) return null;
              const pct = Math.min(period.percentage, 100);
              return (
                <View key={key} style={{ gap: spacing.xs }}>
                  <View
                    style={{
                      flexDirection: "row",
                      justifyContent: "space-between",
                    }}
                  >
                    <Text style={{ fontSize: fontSize.sm }}>{tok.title}</Text>
                    <Text style={{ fontSize: fontSize.xs, color: "#8e8e93" }}>
                      {period.total_tokens.toLocaleString()} /{" "}
                      {period.limit.toLocaleString()}
                    </Text>
                  </View>
                  <View
                    style={{
                      height: 6,
                      borderRadius: 3,
                      backgroundColor: "rgba(255,255,255,0.1)",
                      overflow: "hidden",
                    }}
                  >
                    <View
                      style={{
                        height: "100%",
                        width: `${pct}%`,
                        borderRadius: 3,
                        backgroundColor:
                          pct >= 90
                            ? "#ef4444"
                            : pct >= 70
                              ? "#f59e0b"
                              : "#16c1ff",
                      }}
                    />
                  </View>
                </View>
              );
            })}
          </View>
        </View>
      )}
    </ScrollView>
  );
}
