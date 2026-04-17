import type { RateLimitData } from "@gaia/shared";
import { Pressable, View } from "react-native";
import {
  Alert01Icon,
  AppIcon,
  CheckmarkCircle02Icon,
  Clock01Icon,
  UploadCircle01Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { ToolCardShell } from "@/features/chat/tool-data/primitives";

// -- Helpers -----------------------------------------------------------------

interface ResetInfo {
  label: string;
  detail: string;
}

function getResetInfo(resetTime?: string): ResetInfo | null {
  if (!resetTime) return null;
  const reset = new Date(resetTime);
  const diffMs = reset.getTime() - Date.now();
  if (diffMs <= 0) {
    return {
      label: "Resets very soon",
      detail: "Your limit will refresh shortly.",
    };
  }
  const diffMins = Math.ceil(diffMs / 60_000);
  if (diffMins > 60) {
    const hours = Math.ceil(diffMins / 60);
    return {
      label: `Resets in ${hours} hour${hours !== 1 ? "s" : ""}`,
      detail: `Available again at ${reset.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`,
    };
  }
  return {
    label: `Resets in ${diffMins} minute${diffMins !== 1 ? "s" : ""}`,
    detail: `Available again at ${reset.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`,
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

// -- Card --------------------------------------------------------------------

interface RateLimitCardProps {
  data: RateLimitData;
  onUpgrade?: () => void;
}

export function RateLimitCard({ data, onUpgrade }: RateLimitCardProps) {
  const { feature, plan_required, reset_time } = data;
  const isUpgradeRequired = !!plan_required;
  const resetInfo = getResetInfo(reset_time);
  const featureName = formatFeatureName(feature);
  const planName = plan_required?.toUpperCase() ?? "PRO";

  return (
    <ToolCardShell>
      {/* Header */}
      <View className="flex-row items-start justify-between gap-3 mb-4">
        <View className="flex-row items-center gap-3 flex-1 min-w-0">
          <View
            className={`w-10 h-10 rounded-xl items-center justify-center shrink-0 ${
              isUpgradeRequired ? "bg-amber-500/15" : "bg-red-500/15"
            }`}
          >
            <AppIcon
              icon={isUpgradeRequired ? UploadCircle01Icon : Clock01Icon}
              size={20}
              color={isUpgradeRequired ? "#f59e0b" : "#f87171"}
            />
          </View>
          <View className="flex-1 min-w-0">
            <Text className="text-sm font-semibold text-zinc-100 leading-tight">
              {featureName}
            </Text>
            <Text className="text-xs text-zinc-500 mt-0.5">
              {isUpgradeRequired
                ? `Requires ${planName} plan`
                : "Daily limit reached"}
            </Text>
          </View>
        </View>

        {/* Badge */}
        <View
          className={`px-2.5 py-1 rounded-full shrink-0 ${
            isUpgradeRequired ? "bg-amber-500/15" : "bg-red-500/15"
          }`}
        >
          <Text
            className="text-xs font-semibold"
            style={{ color: isUpgradeRequired ? "#f59e0b" : "#f87171" }}
          >
            {isUpgradeRequired ? planName : "Limit Hit"}
          </Text>
        </View>
      </View>

      {/* Divider */}
      <View className="h-px bg-zinc-700/50 mb-4" />

      {/* Body */}
      {isUpgradeRequired ? (
        <View className="gap-3 mb-4">
          {/* Explanation */}
          <Text className="text-xs leading-relaxed text-zinc-400">
            <Text className="font-medium text-zinc-200">{featureName}</Text> is
            a <Text className="font-medium text-amber-400">{planName}</Text>{" "}
            feature and isn&apos;t included in your current plan. Upgrade to
            unlock it and get significantly higher limits across every feature.
          </Text>

          {/* Benefits */}
          <View className="gap-1.5">
            {PRO_BENEFITS.map((benefit) => (
              <View key={benefit} className="flex-row items-start gap-2">
                <AppIcon
                  icon={CheckmarkCircle02Icon}
                  size={14}
                  color="#00bbff"
                />
                <Text className="text-xs text-zinc-400 flex-1">{benefit}</Text>
              </View>
            ))}
          </View>
        </View>
      ) : (
        <View className="gap-3 mb-4">
          {/* What happened */}
          <Text className="text-xs leading-relaxed text-zinc-400">
            You&apos;ve used all your{" "}
            <Text className="font-medium text-zinc-200">{featureName}</Text>{" "}
            calls for today. Your limit will automatically reset — no action
            needed.
          </Text>

          {/* Reset time block */}
          {resetInfo && (
            <View className="flex-row items-center gap-3 rounded-xl bg-zinc-700 px-3 py-2.5">
              <AppIcon icon={Clock01Icon} size={16} color="#a1a1aa" />
              <View className="gap-0.5">
                <Text className="text-xs font-medium text-zinc-200">
                  {resetInfo.label}
                </Text>
                <Text className="text-[11px] text-zinc-400">
                  {resetInfo.detail}
                </Text>
              </View>
            </View>
          )}

          {/* Upgrade nudge */}
          <View className="flex-row items-start gap-2 px-3">
            <AppIcon icon={Alert01Icon} size={14} color="#a1a1aa" />
            <Text className="text-xs text-zinc-400 flex-1">
              Need more? Upgrade to{" "}
              <Text className="font-medium text-zinc-300">PRO</Text> for 10x
              higher daily limits on {featureName} and all other features.
            </Text>
          </View>
        </View>
      )}

      {/* Divider */}
      <View className="h-px bg-zinc-700/50 mb-3" />

      {/* Footer CTA */}
      <Pressable
        onPress={onUpgrade}
        android_ripple={{ color: "rgba(255,255,255,0.1)" }}
        className={`rounded-xl py-2.5 items-center ${
          isUpgradeRequired ? "bg-[#00bbff]" : "bg-[#00bbff]/15"
        }`}
      >
        <Text
          className={`text-sm font-medium ${
            isUpgradeRequired ? "text-black" : "text-[#00bbff]"
          }`}
        >
          {isUpgradeRequired ? `Upgrade to ${planName}` : "View Plans"}
        </Text>
      </Pressable>
    </ToolCardShell>
  );
}
