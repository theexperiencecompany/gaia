import { Button, Card, Spinner } from "heroui-native";
import { useEffect, useState } from "react";
import { Alert, Linking, ScrollView, View } from "react-native";
import { Text } from "@/components/ui/text";
import type { UsageSummary } from "@/features/settings/api/settings-api";
import { settingsApi } from "@/features/settings/api/settings-api";
import { useResponsive } from "@/lib/responsive";

const C = {
  bg: "#18181b",
  trackBg: "#27272a",
  primary: "#00bbff",
  danger: "#ef4444",
  text: "#e4e4e7",
  textMuted: "#8e8e93",
  textSubtle: "#5a5a5e",
};

interface UsageBarProps {
  label: string;
  used: number;
  limit: number;
}

function UsageBar({ label, used, limit }: UsageBarProps) {
  const { spacing, fontSize } = useResponsive();
  const pct = limit > 0 ? Math.min((used / limit) * 100, 100) : 0;
  const fillColor = pct > 80 ? C.danger : C.primary;

  return (
    <View style={{ gap: spacing.xs }}>
      <View
        style={{
          flexDirection: "row",
          alignItems: "center",
          justifyContent: "space-between",
        }}
      >
        <Text style={{ fontSize: fontSize.sm, color: C.text }}>{label}</Text>
        <Text style={{ fontSize: fontSize.xs, color: C.textMuted }}>
          {used} / {limit}
        </Text>
      </View>
      <View
        style={{
          height: 6,
          borderRadius: 3,
          backgroundColor: C.trackBg,
          overflow: "hidden",
        }}
      >
        <View
          style={{
            height: "100%",
            width: `${pct}%`,
            borderRadius: 3,
            backgroundColor: fillColor,
          }}
        />
      </View>
    </View>
  );
}

export function SubscriptionSection() {
  const { spacing, fontSize } = useResponsive();
  const [summary, setSummary] = useState<UsageSummary | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setIsLoading(true);
    settingsApi
      .getUsageSummary()
      .then((data) => {
        if (!cancelled) setSummary(data);
      })
      .catch(() => {
        if (!cancelled) Alert.alert("Error", "Failed to load subscription.");
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
        <Text style={{ color: C.textMuted, textAlign: "center" }}>
          No subscription data available.
        </Text>
      </View>
    );
  }

  const isPro = summary.plan_type !== "free";
  const planLabel = summary.plan_type
    ? summary.plan_type.charAt(0).toUpperCase() + summary.plan_type.slice(1)
    : "Free";

  // Gather message usage from features if available
  const messageFeature = Object.values(summary.features).find(
    (f) =>
      f.title.toLowerCase().includes("message") ||
      f.category.toLowerCase().includes("message"),
  );
  const dayPeriod = messageFeature?.periods.day;

  const handleCta = async () => {
    try {
      await Linking.openURL("https://gaia.app/pricing");
    } catch {
      Alert.alert("Error", "Could not open link.");
    }
  };

  return (
    <ScrollView
      showsVerticalScrollIndicator={false}
      contentContainerStyle={{
        padding: spacing.md,
        gap: spacing.lg,
        paddingBottom: 40,
      }}
    >
      {/* Plan card */}
      <Card variant="secondary" className="rounded-3xl bg-surface">
        <Card.Body className="gap-3 px-5 py-5">
          <View
            style={{
              flexDirection: "row",
              alignItems: "center",
              justifyContent: "space-between",
            }}
          >
            <Text
              style={{
                fontSize: fontSize.lg,
                fontWeight: "700",
                color: C.text,
              }}
            >
              {planLabel} Plan
            </Text>
            <View
              style={{
                borderRadius: 999,
                paddingHorizontal: 10,
                paddingVertical: 4,
                backgroundColor: isPro
                  ? "rgba(0,187,255,0.2)"
                  : "rgba(255,255,255,0.08)",
              }}
            >
              <Text
                style={{
                  fontSize: fontSize.xs,
                  fontWeight: "700",
                  color: isPro ? C.primary : C.textMuted,
                }}
              >
                {isPro ? "ACTIVE" : "FREE TIER"}
              </Text>
            </View>
          </View>

          <Text style={{ fontSize: fontSize.sm, color: C.textMuted }}>
            {isPro
              ? "Full access to all GAIA features"
              : "Limited usage — upgrade for higher limits"}
          </Text>
        </Card.Body>
      </Card>

      {/* Usage meter */}
      {dayPeriod ? (
        <Card variant="secondary" className="rounded-3xl bg-surface">
          <Card.Body className="gap-4 px-5 py-5">
            <Text
              style={{
                fontSize: fontSize.xs,
                color: C.textMuted,
                textTransform: "uppercase",
                letterSpacing: 1,
              }}
            >
              Daily Usage
            </Text>
            <UsageBar
              label="Messages used"
              used={dayPeriod.used}
              limit={dayPeriod.limit}
            />
          </Card.Body>
        </Card>
      ) : null}

      <Button
        onPress={() => {
          void handleCta();
        }}
        variant={isPro ? "tertiary" : "primary"}
        className={isPro ? "bg-white/10" : "bg-primary"}
      >
        <Button.Label>
          {isPro ? "Manage Subscription" : "Upgrade to Pro"}
        </Button.Label>
      </Button>
    </ScrollView>
  );
}
