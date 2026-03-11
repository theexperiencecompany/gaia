import { useRouter } from "expo-router";
import { useCallback, useRef } from "react";
import { Pressable, View } from "react-native";
import { AlertCircleIcon, ConnectIcon } from "@/components/icons";
import { AppIcon } from "@/components/icons/app-icon";
import { Text } from "@/components/ui/text";
import { getToolCategoryIcon } from "@/features/chat/utils/tool-icons";
import { connectIntegration } from "@/features/integrations/api";
import {
  BearerTokenSheet,
  type BearerTokenSheetRef,
} from "@/features/integrations/components/BearerTokenSheet";

export interface IntegrationConnectionData {
  // API sends integration_id; integration_name is a fallback for older payloads
  integration_id?: string;
  integration_name?: string;
  message?: string;
  connect_url?: string;
  auth_type?: "oauth" | "bearer" | "none";
  icon_url?: string;
}

function formatIntegrationName(id?: string): string {
  if (!id) return "Integration";
  return id.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export function IntegrationConnectionCard({
  data,
}: {
  data: IntegrationConnectionData;
}) {
  const router = useRouter();
  const bearerSheetRef = useRef<BearerTokenSheetRef>(null);

  const integrationId = data.integration_id ?? data.integration_name ?? "";
  const displayName =
    data.integration_name ?? formatIntegrationName(data.integration_id);
  const authType = data.auth_type ?? "oauth";

  const icon = integrationId
    ? getToolCategoryIcon(integrationId, {
        size: 20,
        showBackground: false,
      })
    : null;

  const handleConnectNow = useCallback(() => {
    if (authType === "bearer") {
      bearerSheetRef.current?.open({
        integrationId,
        integrationName: displayName,
        iconUrl: data.icon_url,
      });
    } else {
      // OAuth or none — launch the browser flow
      void connectIntegration(integrationId);
    }
  }, [authType, integrationId, displayName, data.icon_url]);

  const handleSkip = useCallback(() => {
    // Dismiss the card by navigating back or doing nothing.
    // In chat context, "skip" means the user acknowledges and continues.
  }, []);

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
        {/* Header: icon + name + "Not Connected" label */}
        <View
          style={{
            flexDirection: "row",
            alignItems: "flex-start",
            gap: 12,
            marginBottom: 12,
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
              <View
                style={{
                  borderRadius: 999,
                  backgroundColor: "rgba(234,179,8,0.1)",
                  paddingHorizontal: 8,
                  paddingVertical: 2,
                }}
              >
                <Text style={{ fontSize: 11, color: "#eab308" }}>
                  Not Connected
                </Text>
              </View>
            </View>
            <Text style={{ fontSize: 12, color: "#71717a", marginTop: 2 }}>
              This requires {displayName} to be connected
            </Text>
          </View>
        </View>

        {/* Warning message */}
        {data.message && (
          <View
            style={{
              flexDirection: "row",
              alignItems: "flex-start",
              gap: 8,
              borderRadius: 12,
              backgroundColor: "rgba(234,179,8,0.05)",
              borderWidth: 1,
              borderColor: "rgba(234,179,8,0.15)",
              padding: 12,
              marginBottom: 12,
            }}
          >
            <AppIcon icon={AlertCircleIcon} size={14} color="#eab308" />
            <Text
              style={{
                fontSize: 12,
                color: "rgba(234,179,8,0.9)",
                flex: 1,
                lineHeight: 18,
              }}
            >
              {data.message}
            </Text>
          </View>
        )}

        {/* Action buttons */}
        <View style={{ flexDirection: "row", gap: 8 }}>
          {/* Connect Now */}
          <Pressable
            onPress={handleConnectNow}
            style={({ pressed }) => ({
              flex: 1,
              alignItems: "center",
              justifyContent: "center",
              paddingVertical: 10,
              borderRadius: 10,
              backgroundColor: pressed
                ? "rgba(0,170,230,0.9)"
                : "rgba(0,187,255,0.85)",
            })}
          >
            <Text style={{ fontSize: 13, fontWeight: "600", color: "#fff" }}>
              Connect Now
            </Text>
          </Pressable>

          {/* Manage */}
          <Pressable
            onPress={handleManage}
            style={({ pressed }) => ({
              paddingHorizontal: 14,
              paddingVertical: 10,
              borderRadius: 10,
              backgroundColor: pressed
                ? "rgba(255,255,255,0.1)"
                : "rgba(255,255,255,0.06)",
            })}
          >
            <Text style={{ fontSize: 13, fontWeight: "500", color: "#a1a1aa" }}>
              Manage
            </Text>
          </Pressable>

          {/* Skip */}
          <Pressable
            onPress={handleSkip}
            style={({ pressed }) => ({
              paddingHorizontal: 14,
              paddingVertical: 10,
              borderRadius: 10,
              backgroundColor: pressed
                ? "rgba(255,255,255,0.06)"
                : "transparent",
            })}
          >
            <Text style={{ fontSize: 13, fontWeight: "400", color: "#71717a" }}>
              Skip
            </Text>
          </Pressable>
        </View>
      </View>

      {/* BearerTokenSheet mounted here so it has access to the card context */}
      <BearerTokenSheet ref={bearerSheetRef} />
    </View>
  );
}
