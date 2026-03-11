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
  { label: string; color: string; bgColor: string }
> = {
  connected: {
    label: "Connected",
    color: "#34c759",
    bgColor: "rgba(52,199,89,0.1)",
  },
  disconnected: {
    label: "Disconnected",
    color: "#8e8e93",
    bgColor: "rgba(142,142,147,0.1)",
  },
  error: {
    label: "Connection Error",
    color: "#ef4444",
    bgColor: "rgba(239,68,68,0.1)",
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
    <View
      style={{
        marginHorizontal: 16,
        marginVertical: 8,
        borderRadius: 16,
        backgroundColor: "#171920",
        overflow: "hidden",
      }}
    >
      <View style={{ padding: 16 }}>
        {/* Header: icon + name + status badge */}
        <View
          style={{
            flexDirection: "row",
            alignItems: "flex-start",
            gap: 12,
            marginBottom: data.message || data.error_detail ? 12 : 0,
          }}
        >
          <View
            style={{
              width: 36,
              height: 36,
              borderRadius: 12,
              backgroundColor: "rgba(255,255,255,0.05)",
              alignItems: "center",
              justifyContent: "center",
              flexShrink: 0,
            }}
          >
            {icon ?? <AppIcon icon={ConnectIcon} size={18} color="#a1a1aa" />}
          </View>

          <View style={{ flex: 1 }}>
            <View
              style={{
                flexDirection: "row",
                alignItems: "center",
                gap: 8,
                flexWrap: "wrap",
              }}
            >
              <Text
                style={{
                  fontSize: 14,
                  fontWeight: "600",
                  color: "#f4f4f5",
                }}
              >
                {displayName}
              </Text>
              {/* Status badge */}
              <View
                style={{
                  flexDirection: "row",
                  alignItems: "center",
                  gap: 4,
                  borderRadius: 999,
                  backgroundColor: statusConfig.bgColor,
                  paddingHorizontal: 8,
                  paddingVertical: 2,
                }}
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
                  <View
                    style={{
                      width: 6,
                      height: 6,
                      borderRadius: 3,
                      backgroundColor: statusConfig.color,
                    }}
                  />
                )}
                <Text
                  style={{
                    fontSize: 11,
                    color: statusConfig.color,
                    fontWeight: "500",
                  }}
                >
                  {statusConfig.label}
                </Text>
              </View>
            </View>
            {data.message && (
              <Text style={{ fontSize: 12, color: "#71717a", marginTop: 2 }}>
                {data.message}
              </Text>
            )}
          </View>
        </View>

        {/* Error detail block */}
        {data.error_detail && (
          <View
            style={{
              flexDirection: "row",
              alignItems: "flex-start",
              gap: 8,
              borderRadius: 12,
              backgroundColor: "rgba(239,68,68,0.06)",
              borderWidth: 1,
              borderColor: "rgba(239,68,68,0.15)",
              padding: 12,
              marginBottom: 12,
            }}
          >
            <AppIcon icon={AlertCircleIcon} size={14} color="#ef4444" />
            <Text
              style={{
                fontSize: 12,
                color: "rgba(239,68,68,0.9)",
                flex: 1,
                lineHeight: 18,
              }}
            >
              {data.error_detail}
            </Text>
          </View>
        )}

        {/* Manage button */}
        <Pressable
          onPress={handleManage}
          style={({ pressed }) => ({
            alignItems: "center",
            justifyContent: "center",
            paddingVertical: 10,
            borderRadius: 10,
            borderWidth: 1,
            borderColor: "rgba(255,255,255,0.1)",
            backgroundColor: pressed
              ? "rgba(255,255,255,0.08)"
              : "rgba(255,255,255,0.04)",
          })}
        >
          <Text style={{ fontSize: 13, fontWeight: "500", color: "#a1a1aa" }}>
            Manage Integrations
          </Text>
        </Pressable>
      </View>
    </View>
  );
}
