import { useCallback, useRef } from "react";
import { Pressable, View } from "react-native";
import { AlertCircleIcon, ConnectIcon } from "@/components/icons";
import { AppIcon } from "@/components/icons/app-icon";
import { Text } from "@/components/ui/text";
import { ToolCardShell } from "@/features/chat/tool-data/primitives";
import { getToolCategoryIcon } from "@/features/chat/utils/tool-icons";
import { connectIntegration } from "@/features/integrations/api/integrations-api";
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
  description?: string;
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

  const handleConnect = useCallback(() => {
    if (authType === "bearer") {
      bearerSheetRef.current?.open({
        integrationId,
        integrationName: displayName,
        iconUrl: data.icon_url,
      });
    } else {
      void connectIntegration(integrationId);
    }
  }, [authType, integrationId, displayName, data.icon_url]);

  return (
    <ToolCardShell>
      {/* Header: icon + name + "Not Connected" badge */}
      <View className="flex-row items-start gap-3 mb-3">
        <View className="w-9 h-9 rounded-xl bg-zinc-700 items-center justify-center shrink-0">
          {icon ?? <AppIcon icon={ConnectIcon} size={18} color="#a1a1aa" />}
        </View>

        <View className="flex-1">
          <View className="flex-row items-center gap-2 flex-wrap">
            <Text className="text-zinc-100 text-sm font-semibold">
              {displayName}
            </Text>
            <View className="rounded-full bg-amber-400/10 px-2 py-0.5">
              <Text className="text-amber-400 text-[11px]">Not Connected</Text>
            </View>
          </View>
          {data.description ? (
            <Text className="text-zinc-400 text-xs mt-0.5" numberOfLines={2}>
              {data.description}
            </Text>
          ) : (
            <Text className="text-zinc-500 text-xs mt-0.5">
              This requires {displayName} to be connected
            </Text>
          )}
        </View>
      </View>

      {/* Warning message */}
      {data.message ? (
        <View className="flex-row items-start gap-2 rounded-xl bg-amber-400/5 p-3 mb-3">
          <AppIcon icon={AlertCircleIcon} size={14} color="#fbbf24" />
          <Text className="text-amber-400 text-xs flex-1 leading-[18px]">
            {data.message}
          </Text>
        </View>
      ) : null}

      {/* Connect button — matches web: single primary action */}
      <Pressable
        onPress={handleConnect}
        className="rounded-xl bg-primary items-center justify-center py-2.5"
        android_ripple={{ color: "rgba(0,0,0,0.1)" }}
      >
        <Text className="text-black text-sm font-semibold">Connect</Text>
      </Pressable>

      <BearerTokenSheet ref={bearerSheetRef} />
    </ToolCardShell>
  );
}
