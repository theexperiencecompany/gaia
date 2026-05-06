import { Skeleton } from "heroui-native";
import { View } from "react-native";
import {
  AppIcon,
  CheckmarkCircle02Icon,
  InformationCircleIcon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import type { Integration } from "../types";

interface IntegrationStatusPillProps {
  status: Integration["status"];
  isPending?: boolean;
}

/**
 * Single canonical status pill used in both the row and the detail sheet.
 */
export function IntegrationStatusPill({
  status,
  isPending,
}: IntegrationStatusPillProps) {
  if (isPending) {
    return <Skeleton className="h-6 w-20 rounded-full" />;
  }

  if (status === "connected") {
    return (
      <View className="flex-row items-center gap-1 rounded-full bg-primary/10 px-2.5 py-1">
        <AppIcon icon={CheckmarkCircle02Icon} size={11} color="#00bbff" />
        <Text className="text-[11px] font-semibold text-primary">
          Connected
        </Text>
      </View>
    );
  }

  if (status === "error") {
    return (
      <View className="flex-row items-center gap-1 rounded-full bg-red-500/10 px-2.5 py-1">
        <AppIcon icon={InformationCircleIcon} size={11} color="#ef4444" />
        <Text className="text-[11px] font-semibold text-red-500">Error</Text>
      </View>
    );
  }

  if (status === "created") {
    return (
      <View className="rounded-full bg-amber-500/10 px-2.5 py-1">
        <Text className="text-[11px] font-semibold text-amber-500">
          Pending
        </Text>
      </View>
    );
  }

  return (
    <View className="rounded-full bg-zinc-800/50 px-2.5 py-1">
      <Text className="text-[11px] font-medium text-zinc-400">
        Not Connected
      </Text>
    </View>
  );
}
