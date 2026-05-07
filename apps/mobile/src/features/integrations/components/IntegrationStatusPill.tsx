import { Skeleton } from "heroui-native";
import { View } from "react-native";
import { Text } from "@/components/ui/text";
import type { Integration } from "../types";

interface IntegrationStatusPillProps {
  status: Integration["status"];
  isPending?: boolean;
}

/**
 * Small flat status chip used inside the detail sheet header.
 * Mirrors the web `Chip variant="flat" color="success"` pattern used in
 * `apps/web/src/features/integrations/components/IntegrationsList.tsx` so
 * the row stays consistent with the desktop integrations page.
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
      <View className="rounded-full bg-success/15 px-2.5 py-1">
        <Text className="text-[11px] font-semibold text-success">
          Connected
        </Text>
      </View>
    );
  }

  if (status === "error") {
    return (
      <View className="rounded-full bg-red-500/10 px-2.5 py-1">
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

  return null;
}
