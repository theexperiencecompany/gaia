import { useRouter } from "expo-router";
import { useCallback } from "react";
import { Pressable, View } from "react-native";
import {
  AlertCircleIcon,
  CheckmarkCircle02Icon,
  ConnectIcon,
} from "@/components/icons";
import { AppIcon } from "@/components/icons/app-icon";
import { Text } from "@/components/ui/text";
import { ToolCardShell } from "@/features/chat/tool-data/primitives";
import { getToolCategoryIcon } from "@/features/chat/utils/tool-icons";

export type ConnectionStatus = "connected" | "disconnected" | "error";

export interface ConnectionStatusData {
  integration_id?: string;
  integration_name?: string;
  status: ConnectionStatus;
  message?: string;
  icon_url?: string;
  error_detail?: string;
}

function formatIntegrationName(id?: string): string {
  if (!id) return "Integration";
  return id.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

const STATUS_CONFIG: Record<
  ConnectionStatus,
  { label: string; color: string; bgClass: string; textClass: string }
> = {
  connected: {
    label: "Connected",
    color: "#22c55e",
    bgClass: "bg-green-500/10",
    textClass: "text-green-400",
  },
  disconnected: {
    label: "Disconnected",
    color: "#71717a",
    bgClass: "bg-zinc-700",
    textClass: "text-zinc-400",
  },
  error: {
    label: "Connection Error",
    color: "#ef4444",
    bgClass: "bg-red-500/10",
    textClass: "text-red-400",
  },
};

export function ConnectionStatusCard({ data }: { data: ConnectionStatusData }) {
  const router = useRouter();

  const integrationId = data.integration_id ?? data.integration_name ?? "";
  const displayName =
    data.integration_name ?? formatIntegrationName(data.integration_id);
  const statusConfig = STATUS_CONFIG[data.status];

  const icon = integrationId
    ? getToolCategoryIcon(integrationId, {
        size: 20,
        showBackground: false,
      })
    : null;

  const handleManage = useCallback(() => {
    router.push("/(app)/(tabs)/integrations");
  }, [router]);

  return (
    <ToolCardShell>
      {/* Header: icon + name + status badge */}
      <View
        className={`flex-row items-start gap-3 ${data.message || data.error_detail ? "mb-3" : "mb-3"}`}
      >
        <View className="w-9 h-9 rounded-xl bg-zinc-700 items-center justify-center shrink-0">
          {icon ?? <AppIcon icon={ConnectIcon} size={18} color="#a1a1aa" />}
        </View>

        <View className="flex-1">
          <View className="flex-row items-center gap-2 flex-wrap">
            <Text className="text-zinc-100 text-sm font-semibold">
              {displayName}
            </Text>
            {/* Status badge */}
            <View
              className={`flex-row items-center gap-1 rounded-full px-2 py-0.5 ${statusConfig.bgClass}`}
            >
              {data.status === "connected" ? (
                <AppIcon
                  icon={CheckmarkCircle02Icon}
                  size={10}
                  color={statusConfig.color}
                />
              ) : data.status === "error" ? (
                <AppIcon
                  icon={AlertCircleIcon}
                  size={10}
                  color={statusConfig.color}
                />
              ) : (
                <View className="w-1.5 h-1.5 rounded-full bg-zinc-400" />
              )}
              <Text
                className={`text-[11px] font-medium ${statusConfig.textClass}`}
              >
                {statusConfig.label}
              </Text>
            </View>
          </View>

          {data.message ? (
            <Text className="text-zinc-500 text-xs mt-0.5">{data.message}</Text>
          ) : null}
        </View>
      </View>

      {/* Error detail block — no border, bg contrast only */}
      {data.error_detail ? (
        <View className="flex-row items-start gap-2 rounded-xl bg-red-500/5 p-3 mb-3">
          <AppIcon icon={AlertCircleIcon} size={14} color="#ef4444" />
          <Text className="text-red-400 text-xs flex-1 leading-[18px]">
            {data.error_detail}
          </Text>
        </View>
      ) : null}

      {/* Manage button */}
      <Pressable
        onPress={handleManage}
        className="rounded-xl bg-zinc-700 items-center justify-center py-2.5"
        android_ripple={{ color: "rgba(255,255,255,0.05)" }}
      >
        <Text className="text-zinc-300 text-sm font-medium">
          Manage Integrations
        </Text>
      </Pressable>
    </ToolCardShell>
  );
}
