import { Button, Chip } from "heroui-native";
import { useCallback, useRef } from "react";
import { View } from "react-native";
import { AlertCircleIcon, ConnectIcon } from "@/components/icons";
import { AppIcon } from "@/components/icons/app-icon";
import { Text } from "@/components/ui/text";
import { CollapsibleCard } from "@/features/chat/tool-data/primitives";
import { getToolCategoryIcon } from "@/features/chat/utils/tool-icons";
import {
  BearerTokenSheet,
  type BearerTokenSheetRef,
} from "@/features/integrations/components/BearerTokenSheet";
import { useIntegrations } from "@/features/integrations/hooks/useIntegrations";

// Web-aligned shape: server payload only carries integration_id + message.
// All visual fields (name, description, status, available, authType) are
// resolved from the live integrations list, mirroring web's
// IntegrationConnectionPrompt behaviour.
export interface IntegrationConnectionData {
  integration_id: string;
  message: string;
  // Optional fields tolerated for backward compat with older payloads
  integration_name?: string;
  icon_url?: string;
  connect_url?: string;
}

interface IntegrationConnectionCardProps {
  data: IntegrationConnectionData;
  /** Optional override — defaults to useIntegrations().connect */
  onConnect?: (integrationId: string) => Promise<unknown> | undefined;
}

export function IntegrationConnectionCard({
  data,
  onConnect,
}: IntegrationConnectionCardProps) {
  const { integration_id, message } = data;
  const { integrations, connect } = useIntegrations();
  const bearerSheetRef = useRef<BearerTokenSheetRef>(null);

  const integration = integrations.find((i) => i.id === integration_id);

  const handleConnect = useCallback(async () => {
    if (!integration) return;
    try {
      if (integration.authType === "bearer") {
        bearerSheetRef.current?.open({
          integrationId: integration.id,
          integrationName: integration.name,
          iconUrl: integration.iconUrl,
        });
        return;
      }
      if (onConnect) {
        await onConnect(integration.id);
      } else {
        await connect(integration.id);
      }
    } catch (error) {
      console.error("Failed to connect integration:", error);
    }
  }, [connect, integration, onConnect]);

  // Match web: silent null when integration not in the list yet.
  if (!integration) {
    return null;
  }

  const isConnected = integration.status === "connected";
  const isAvailable =
    integration.source === "custom" || !!integration.available;

  const headerIcon = getToolCategoryIcon(integration_id, {
    size: 20,
    showBackground: false,
  });

  return (
    <>
      <CollapsibleCard
        customIcon={headerIcon ?? undefined}
        icon={headerIcon ? undefined : ConnectIcon}
        iconSize={20}
        title={(open) => `${open ? "Hide" : "Show"} 1 Integration Required`}
        titleTone="muted"
      >
        <View className="rounded-2xl bg-zinc-900 p-3">
          {/* Header — icon + name + status chip + description */}
          <View className="flex-row items-start gap-3">
            <View className="shrink-0 pt-0.5">
              {getToolCategoryIcon(integration_id, {
                size: 22,
                showBackground: false,
              })}
            </View>

            <View className="min-w-0 flex-1 gap-1">
              <View className="flex-row items-center gap-2 flex-wrap">
                <Text className="text-zinc-100 text-sm font-medium">
                  {integration.name}
                </Text>
                {isConnected ? (
                  <Chip
                    size="sm"
                    variant="soft"
                    color="success"
                    animation="disable-all"
                  >
                    <Chip.Label>Connected</Chip.Label>
                  </Chip>
                ) : (
                  <Chip
                    size="sm"
                    variant="soft"
                    color="warning"
                    animation="disable-all"
                  >
                    <Chip.Label>Not Connected</Chip.Label>
                  </Chip>
                )}
              </View>

              <Text className="text-zinc-400 text-xs" numberOfLines={3}>
                {integration.description}
              </Text>
            </View>
          </View>

          {/* Warning + Connect — only when not connected and available */}
          {!isConnected && isAvailable ? (
            <View className="mt-3 gap-2">
              <View className="flex-row items-start gap-2 rounded-xl bg-amber-400/10 p-3">
                <View className="pt-0.5">
                  <AppIcon icon={AlertCircleIcon} size={16} color="#facc15" />
                </View>
                <Text className="text-amber-300 text-xs flex-1 leading-[18px]">
                  {message}
                </Text>
              </View>

              <Button
                size="sm"
                variant="primary"
                onPress={() => {
                  void handleConnect();
                }}
              >
                <Button.Label>Connect</Button.Label>
              </Button>
            </View>
          ) : null}
        </View>
      </CollapsibleCard>

      <BearerTokenSheet ref={bearerSheetRef} />
    </>
  );
}
