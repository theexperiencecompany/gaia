import {
  USAGE_DANGER_THRESHOLD,
  USAGE_WARN_THRESHOLD,
} from "@gaia/shared/constants/usage";
import { Button, Card, Chip, Spinner } from "heroui-native";
import { useEffect, useState } from "react";
import { Alert, Linking, ScrollView, View } from "react-native";
import { Text } from "@/components/ui/text";
import type {
  BudgetWindow,
  UsagePeriod,
  UsageSummary,
} from "@/features/settings/api/settings-api";
import { settingsApi } from "@/features/settings/api/settings-api";
import { PRICING_URL } from "@/lib/constants";
import { colors } from "@/lib/design-tokens";
import { useResponsive } from "@/lib/responsive";

type PeriodKey = "day" | "month";

/** Mobile usage-bar accent — its own blue, distinct from web's meter accent. */
const USAGE_BAR_ACCENT = "#16c1ff";

/** Fill color by percentage: shared warn/danger thresholds, mobile status hues. */
function barColor(percentage: number): string {
  const pct = Math.min(percentage, 100);
  if (pct >= USAGE_DANGER_THRESHOLD) return colors.error;
  if (pct >= USAGE_WARN_THRESHOLD) return colors.warning;
  return USAGE_BAR_ACCENT;
}

interface UsageBarProps {
  title: string;
  period: UsagePeriod | undefined;
}

function UsageBar({ title, period }: UsageBarProps) {
  const { spacing, fontSize } = useResponsive();
  if (!period) return null;

  const pct = Math.min(period.percentage, 100);

  return (
    <View style={{ gap: spacing.xs }}>
      <View style={{ flexDirection: "row", justifyContent: "space-between" }}>
        <Text style={{ fontSize: fontSize.sm }}>{title}</Text>
        <Text style={{ fontSize: fontSize.xs, color: "#71717a" }}>
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
            backgroundColor: barColor(period.percentage),
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

interface BudgetBarProps {
  title: string;
  window: BudgetWindow | null | undefined;
  periodLabel: string;
}

/** The primary feature's meter is its cost-budget percentage, not a message
 * count — chat is priced by usage now, so a raw "N / limit" would be a lie. */
function BudgetBar({ title, window, periodLabel }: BudgetBarProps) {
  const { spacing, fontSize } = useResponsive();
  if (!window) return null;

  const pct = Math.min(window.percentage, 100);

  return (
    <View style={{ gap: spacing.xs }}>
      <View style={{ flexDirection: "row", justifyContent: "space-between" }}>
        <Text style={{ fontSize: fontSize.sm }}>{title}</Text>
        <Text style={{ fontSize: fontSize.xs, color: "#71717a" }}>
          {Math.round(window.percentage)}%
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
            backgroundColor: barColor(window.percentage),
          }}
        />
      </View>

      <Text style={{ fontSize: fontSize.xs - 1, color: "#5a5a5e" }}>
        of {periodLabel} allowance
        {window.reset_time
          ? ` · resets ${new Date(window.reset_time).toLocaleDateString()}`
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
        <Spinner />
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
        <Text style={{ color: "#71717a", textAlign: "center" }}>
          No usage data available.
        </Text>
      </View>
    );
  }

  const primaryKey = summary.primary_feature;
  const primaryTitle = summary.features[primaryKey]?.title ?? "AI Usage";
  const budgetWindow =
    periodKey === "day" ? summary.budget?.daily : summary.budget?.monthly;
  const featureEntries = Object.entries(summary.features).filter(
    ([key, feature]) => key !== primaryKey && feature.periods[periodKey],
  );
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
      <Card variant="secondary" className="rounded-2xl bg-surface">
        <Card.Body className="flex-row items-center justify-between px-4 py-4">
          <View>
            <Text
              style={{
                fontSize: fontSize.xs,
                color: "#71717a",
                textTransform: "uppercase",
                letterSpacing: 1,
              }}
            >
              Plan
            </Text>
            <Text
              style={{
                fontSize: fontSize.base,
                fontWeight: "600",
                marginTop: 2,
              }}
            >
              {isPro ? "Pro" : "No subscription"}
            </Text>
          </View>
          {!isPro ? (
            <Button
              className="bg-primary"
              onPress={() => {
                void Linking.openURL(PRICING_URL);
              }}
            >
              <Button.Label>Subscribe</Button.Label>
            </Button>
          ) : null}
        </Card.Body>
      </Card>

      <View style={{ flexDirection: "row", gap: spacing.sm }}>
        {(["day", "month"] as PeriodKey[]).map((key) => {
          const isActive = periodKey === key;
          return (
            <Chip
              key={key}
              onPress={() => setPeriodKey(key)}
              variant={isActive ? "primary" : "secondary"}
              color={isActive ? "accent" : "default"}
              className={isActive ? "" : "bg-white/10"}
            >
              {key === "day" ? "Daily" : "Monthly"}
            </Chip>
          );
        })}
      </View>

      <Card variant="secondary" className="rounded-2xl bg-surface">
        <Card.Body className="gap-5 px-4 py-4">
          <BudgetBar
            title={primaryTitle}
            window={budgetWindow}
            periodLabel={periodKey === "day" ? "daily" : "monthly"}
          />
          {featureEntries.map(([key, feature]) => (
            <UsageBar
              key={key}
              title={feature.title}
              period={feature.periods[periodKey]}
            />
          ))}
          {!budgetWindow && featureEntries.length === 0 && (
            <Text style={{ color: "#71717a", fontSize: fontSize.sm }}>
              No feature usage data.
            </Text>
          )}
        </Card.Body>
      </Card>
    </ScrollView>
  );
}
