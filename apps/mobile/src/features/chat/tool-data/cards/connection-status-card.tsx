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
import { getToolCategoryIcon } from "@/features/chat/utils/tool-icons";
import { ToolCardShell } from "../primitives";

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

interface StatusBadge {
  label: string;
  badgeClass: string;
  textClass: string;
  iconColor: string;
}

const STATUS_BADGE: Record<ConnectionStatus, StatusBadge> = {
  connected: {
    label: "Connected",
    badgeClass: "bg-green-500/15",
    textClass: "text-green-500",
    iconColor: "#22c55e",
  },
  disconnected: {
    label: "Disconnected",
    badgeClass: "bg-red-500/15",
    textClass: "text-red-500",
    iconColor: "#ef4444",
  },
  error: {
    label: "Connection Error",
    badgeClass: "bg-red-500/15",
    textClass: "text-red-500",
    iconColor: "#ef4444",
  },
};

export function ConnectionStatusCard({ data }: { data: ConnectionStatusData }) {
  const router = useRouter();

  const integrationId = data.integration_id ?? data.integration_name ?? "";
  const displayName =
    data.integration_name ?? formatIntegrationName(data.integration_id);
  const badge = STATUS_BADGE[data.status];

  const icon = integrationId
    ? getToolCategoryIcon(
        integrationId,
        { size: 20, showBackground: false },
        data.icon_url,
      )
    : null;

  const handleManage = useCallback(() => {
    router.push("/(app)/(tabs)/integrations");
  }, [router]);

  return (
    <ToolCardShell>
      {/* Header: icon + name + status badge */}
      <View className="flex-row items-start gap-3">
        <View className="w-8 h-8 rounded-full bg-zinc-700 items-center justify-center shrink-0">
          {icon ?? <AppIcon icon={ConnectIcon} size={16} color="#a1a1aa" />}
        </View>

        <View className="flex-1 min-w-0">
          <View className="flex-row items-center gap-2 flex-wrap">
            <Text
              className="text-sm font-medium text-zinc-100"
              numberOfLines={1}
            >
              {displayName}
            </Text>
            <View
              className={`flex-row items-center gap-1 rounded-full ${badge.badgeClass} px-2 py-0.5`}
            >
              {data.status === "connected" ? (
                <AppIcon
                  icon={CheckmarkCircle02Icon}
                  size={10}
                  color={badge.iconColor}
                />
              ) : (
                <AppIcon
                  icon={AlertCircleIcon}
                  size={10}
                  color={badge.iconColor}
                />
              )}
              <Text className={`text-[11px] font-medium ${badge.textClass}`}>
                {badge.label}
              </Text>
            </View>
          </View>
          {data.message ? (
            <Text className="mt-0.5 text-xs text-zinc-400" numberOfLines={3}>
              {data.message}
            </Text>
          ) : null}
        </View>
      </View>

      {/* Error detail block */}
      {data.error_detail ? (
        <View className="mt-3 flex-row items-start gap-2 rounded-2xl bg-red-500/10 p-3">
          <AppIcon icon={AlertCircleIcon} size={14} color="#ef4444" />
          <Text className="flex-1 text-xs text-red-500 leading-[18px]">
            {data.error_detail}
          </Text>
        </View>
      ) : null}

      {/* Manage button */}
      <Pressable
        onPress={handleManage}
        className="mt-3 items-center justify-center rounded-2xl bg-zinc-700 active:bg-zinc-700/70 py-3"
      >
        <Text className="text-sm font-medium text-zinc-200">
          Manage Integrations
        </Text>
      </Pressable>
    </ToolCardShell>
  );
}
