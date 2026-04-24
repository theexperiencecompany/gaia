import { useRouter } from "expo-router";
import { useCallback } from "react";
import { Pressable, View } from "react-native";
import {
  Alert01Icon,
  AppIcon,
  CheckmarkCircle02Icon,
  Clock01Icon,
  UploadCircle01Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import {
  ToolCardHeader,
  ToolCardInner,
  ToolCardShell,
} from "@/features/chat/tool-data/primitives";

// -- Types --------------------------------------------------------------------

export interface RateLimitData {
  feature: string;
  plan_required?: string;
  reset_time?: string;
}

// -- Helpers ------------------------------------------------------------------

function getResetInfo(
  resetTime?: string,
): { label: string; detail: string } | null {
  if (!resetTime) return null;
  const reset = new Date(resetTime);
  if (Number.isNaN(reset.getTime())) return null;
  const diffMs = reset.getTime() - Date.now();
  if (diffMs <= 0) {
    return {
      label: "Resets very soon",
      detail: "Your limit will refresh shortly.",
    };
  }
  const diffMins = Math.ceil(diffMs / 60000);
  const timeLabel = reset.toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  });
  if (diffMins > 60) {
    const hours = Math.ceil(diffMins / 60);
    return {
      label: `Resets in ${hours} hour${hours !== 1 ? "s" : ""}`,
      detail: `Available again at ${timeLabel}`,
    };
  }
  return {
    label: `Resets in ${diffMins} minute${diffMins !== 1 ? "s" : ""}`,
    detail: `Available again at ${timeLabel}`,
  };
}

function formatFeatureName(feature?: string): string {
  if (!feature) return "This Feature";
  return feature
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

const PRO_BENEFITS = [
  "10x higher daily limits on all features",
  "Priority responses and faster processing",
];

// -- Card ---------------------------------------------------------------------

export function RateLimitCard({ data }: { data: RateLimitData }) {
  const router = useRouter();
  const { feature, plan_required, reset_time } = data;

  const isUpgradeRequired = !!plan_required;
  const resetInfo = getResetInfo(reset_time);
  const featureName = formatFeatureName(feature);
  const planName = plan_required?.toUpperCase() ?? "PRO";

  const handleUpgrade = useCallback(() => {
    router.push("/(app)/settings");
  }, [router]);

  const headerIcon = isUpgradeRequired ? UploadCircle01Icon : Clock01Icon;
  const headerIconColor = isUpgradeRequired ? "#f59e0b" : "#f87171";

  const badge = (
    <View
      className={`rounded-full px-2 py-0.5 ${isUpgradeRequired ? "bg-amber-400/15" : "bg-red-500/15"}`}
    >
      <Text
        className={`text-xs font-semibold ${isUpgradeRequired ? "text-amber-400" : "text-red-400"}`}
      >
        {isUpgradeRequired ? planName : "Limit Hit"}
      </Text>
    </View>
  );

  return (
    <ToolCardShell>
      <ToolCardHeader
        icon={headerIcon}
        iconColor={headerIconColor}
        title={featureName}
        subtitle={
          isUpgradeRequired
            ? `Requires ${planName} plan`
            : "Daily limit reached"
        }
        trailing={badge}
      />

      {isUpgradeRequired ? (
        <View className="gap-3">
          <ToolCardInner>
            <Text className="text-xs leading-relaxed text-zinc-400">
              <Text className="text-xs font-medium text-zinc-200">
                {featureName}
              </Text>
              {" is a "}
              <Text className="text-xs font-medium text-amber-400">
                {planName}
              </Text>
              {" feature and isn"}
              {"'"}
              {"t included in your current plan. Upgrade to unlock it and get significantly higher limits across every feature."}
            </Text>

            <View className="mt-3 gap-1.5">
              {PRO_BENEFITS.map((benefit) => (
                <View key={benefit} className="flex-row items-start gap-2">
                  <View style={{ marginTop: 2 }}>
                    <AppIcon
                      icon={CheckmarkCircle02Icon}
                      size={14}
                      color="#00bbff"
                    />
                  </View>
                  <Text className="flex-1 text-xs text-zinc-400">
                    {benefit}
                  </Text>
                </View>
              ))}
            </View>
          </ToolCardInner>

          <Pressable
            onPress={handleUpgrade}
            className="items-center justify-center rounded-2xl bg-[#00bbff] px-4 py-3 active:opacity-80"
          >
            <Text className="text-sm font-semibold text-white">
              {`Upgrade to ${planName}`}
            </Text>
          </Pressable>
        </View>
      ) : (
        <View className="gap-3">
          <ToolCardInner>
            <Text className="text-xs leading-relaxed text-zinc-400">
              {"You"}
              {"'"}
              {"ve used all your "}
              <Text className="text-xs font-medium text-zinc-200">
                {featureName}
              </Text>
              {" calls for today. Your limit will automatically reset, no action needed."}
            </Text>
          </ToolCardInner>

          {resetInfo && (
            <ToolCardInner>
              <View className="flex-row items-center gap-3">
                <AppIcon icon={Clock01Icon} size={16} color="#a1a1aa" />
                <View className="flex-1">
                  <Text className="text-xs font-medium text-zinc-200">
                    {resetInfo.label}
                  </Text>
                  <Text className="text-[11px] text-zinc-400 mt-0.5">
                    {resetInfo.detail}
                  </Text>
                </View>
              </View>
            </ToolCardInner>
          )}

          <ToolCardInner>
            <View className="flex-row items-start gap-2">
              <View style={{ marginTop: 2 }}>
                <AppIcon icon={Alert01Icon} size={14} color="#a1a1aa" />
              </View>
              <Text className="flex-1 text-xs text-zinc-400">
                {"Need more? Upgrade to "}
                <Text className="text-xs font-medium text-zinc-300">PRO</Text>
                {` for 10x higher daily limits on ${featureName} and all other features.`}
              </Text>
            </View>
          </ToolCardInner>

          <Pressable
            onPress={handleUpgrade}
            className="items-center justify-center rounded-2xl bg-[#00bbff]/15 px-4 py-3 active:opacity-80"
          >
            <Text className="text-sm font-semibold text-[#00bbff]">
              View Plans
            </Text>
          </Pressable>
        </View>
      )}
    </ToolCardShell>
  );
}
