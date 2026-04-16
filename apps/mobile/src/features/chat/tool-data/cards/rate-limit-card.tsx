import type { RateLimitData } from "@gaia/shared";
import { Pressable, View } from "react-native";
import { Alert01Icon, AppIcon } from "@/components/icons";
import { Text } from "@/components/ui/text";
import { ToolCardShell } from "@/features/chat/tool-data/primitives";

const WARNING_COLOR = "#f59e0b";

// -- Helpers -----------------------------------------------------------------

function formatResetTime(resetTime?: string): string | undefined {
  if (!resetTime) return undefined;
  const date = new Date(resetTime);
  if (Number.isNaN(date.getTime())) return resetTime;

  const now = new Date();
  const diffMs = date.getTime() - now.getTime();
  const diffMinutes = Math.round(diffMs / 60_000);

  if (diffMinutes <= 0) return "now";
  if (diffMinutes < 60) {
    return `in ${diffMinutes} minute${diffMinutes !== 1 ? "s" : ""}`;
  }
  const diffHours = Math.round(diffMinutes / 60);
  if (diffHours < 24) {
    return `in ${diffHours} hour${diffHours !== 1 ? "s" : ""}`;
  }
  const diffDays = Math.round(diffHours / 24);
  return `in ${diffDays} day${diffDays !== 1 ? "s" : ""}`;
}

function humanizeFeature(feature: string): string {
  return feature.replace(/_/g, " ").replace(/\b\w/g, (l) => l.toUpperCase());
}

// -- Card --------------------------------------------------------------------

interface RateLimitCardProps {
  data: RateLimitData;
  upgradeUrl?: string;
  onUpgrade?: () => void;
}

export function RateLimitCard({
  data,
  upgradeUrl: _upgradeUrl,
  onUpgrade,
}: RateLimitCardProps) {
  const featureLabel = humanizeFeature(data.feature ?? "this feature");
  const planLabel = data.plan_required
    ? data.plan_required.charAt(0).toUpperCase() + data.plan_required.slice(1)
    : undefined;
  const resetLabel = formatResetTime(data.reset_time);

  return (
    <ToolCardShell>
      <View className="flex-row items-start gap-3">
        <View
          className="w-1 rounded-full self-stretch"
          style={{ backgroundColor: WARNING_COLOR }}
        />
        <View className="flex-1">
          <View className="flex-row items-center gap-2">
            <AppIcon icon={Alert01Icon} size={18} color={WARNING_COLOR} />
            <Text
              className="text-sm font-semibold"
              style={{ color: WARNING_COLOR }}
            >
              Rate limit reached
            </Text>
          </View>
          <Text className="text-zinc-100 text-sm mt-2">
            You've reached the usage limit for{" "}
            <Text className="font-semibold">{featureLabel}</Text>.
          </Text>
          {resetLabel ? (
            <Text className="text-zinc-400 text-xs mt-1">
              Resets {resetLabel}
            </Text>
          ) : null}
          {planLabel ? (
            <Text className="text-zinc-400 text-xs mt-1">
              Upgrade to {planLabel} for more.
            </Text>
          ) : null}

          {onUpgrade ? (
            <Pressable
              onPress={onUpgrade}
              className="mt-3 rounded-xl py-2.5 items-center"
              style={{ backgroundColor: WARNING_COLOR }}
            >
              <Text className="text-black text-sm font-semibold">Upgrade</Text>
            </Pressable>
          ) : null}
        </View>
      </View>
    </ToolCardShell>
  );
}
