import { useCallback, useRef } from "react";
import { Pressable, View } from "react-native";
import { AlertCircleIcon, ConnectIcon } from "@/components/icons";
import { AppIcon } from "@/components/icons/app-icon";
import { Text } from "@/components/ui/text";
import { getToolCategoryIcon } from "@/features/chat/utils/tool-icons";
import {
  BearerTokenSheet,
  type BearerTokenSheetRef,
} from "@/features/integrations/components/BearerTokenSheet";
import { useIntegrations } from "@/features/integrations/hooks/useIntegrations";
import { ToolCardShell } from "../primitives";

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
  const bearerSheetRef = useRef<BearerTokenSheetRef>(null);
  const { integrations, connect } = useIntegrations();

  const integrationId = data.integration_id ?? data.integration_name ?? "";
  const integration = integrations.find((i) => i.id === integrationId);
  const displayName =
    integration?.name ??
    data.integration_name ??
    formatIntegrationName(data.integration_id);
  const description = integration?.description;
  const isConnected = integration?.status === "connected";
  const authType =
    integration?.authType ?? data.auth_type ?? ("oauth" as const);
  const isAvailable =
    integration?.source === "custom" || integration?.available !== false;

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
      return;
    }
    void connect(integrationId);
  }, [authType, integrationId, displayName, data.icon_url, connect]);

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
            {isConnected ? (
              <View className="rounded-full bg-green-500/15 px-2 py-0.5">
                <Text className="text-[11px] font-medium text-green-500">
                  Connected
                </Text>
              </View>
            ) : (
              <View className="rounded-full bg-amber-500/15 px-2 py-0.5">
                <Text className="text-[11px] font-medium text-amber-500">
                  Not Connected
                </Text>
              </View>
            )}
          </View>
          {description ? (
            <Text
              className="text-xs font-light text-zinc-400 mt-0.5"
              numberOfLines={2}
            >
              {description}
            </Text>
          ) : null}
        </View>
      </View>

      {/* Warning message + connect button */}
      {!isConnected && isAvailable ? (
        <View className="mt-3 gap-2">
          {data.message ? (
            <View className="flex-row items-start gap-2 rounded-2xl bg-amber-500/10 p-3">
              <AppIcon icon={AlertCircleIcon} size={14} color="#f59e0b" />
              <Text className="text-xs text-amber-500 flex-1 leading-[18px]">
                {data.message}
              </Text>
            </View>
          ) : null}

          <Pressable
            onPress={handleConnect}
            className="rounded-2xl bg-brand active:bg-brand/90 py-3 items-center justify-center"
          >
            <Text className="text-sm font-semibold text-brand-foreground">
              Connect
            </Text>
          </Pressable>
        </View>
      ) : null}

      <BearerTokenSheet ref={bearerSheetRef} />
    </ToolCardShell>
  );
}
