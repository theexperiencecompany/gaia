import { useRouter } from "expo-router";
import { useCallback } from "react";
import { Pressable, View } from "react-native";
import { ConnectIcon, Tick02Icon } from "@/components/icons";
import { AppIcon } from "@/components/icons/app-icon";
import { Text } from "@/components/ui/text";
import { getToolCategoryIcon } from "@/features/chat/utils/tool-icons";
import { useIntegrations } from "@/features/integrations/hooks/useIntegrations";
import type { Integration } from "@/features/integrations/types";
import { SectionLabel, ToolCardHeader, ToolCardShell } from "../primitives";

export interface SuggestedIntegration {
  id: string;
  name: string;
  description: string;
  category?: string;
  iconUrl?: string | null;
  authType?: string | null;
  relevanceScore?: number;
  slug: string;
}

export interface IntegrationListStreamData {
  hasSuggestions?: boolean;
  suggested?: SuggestedIntegration[];
}

export interface IntegrationListCardData {
  suggested?: SuggestedIntegration[];
}

function IntegrationRow({
  id,
  name,
  description,
  iconUrl,
  isConnected,
  canConnect,
  trailingLabel,
  onPress,
  onAction,
}: {
  id: string;
  name: string;
  description?: string;
  iconUrl?: string | null;
  isConnected: boolean;
  canConnect: boolean;
  trailingLabel?: string;
  onPress: () => void;
  onAction?: () => void;
}) {
  const icon = getToolCategoryIcon(
    id,
    { size: 20, showBackground: false },
    iconUrl,
  );

  return (
    <Pressable
      onPress={onPress}
      className="flex-row items-start gap-3 rounded-2xl bg-zinc-900 p-3 active:bg-zinc-700"
    >
      <View className="w-8 h-8 rounded-full bg-zinc-700 items-center justify-center shrink-0">
        {icon ?? <AppIcon icon={ConnectIcon} size={16} color="#a1a1aa" />}
      </View>

      <View className="flex-1 min-w-0">
        <View className="flex-row items-center gap-2 flex-wrap">
          <Text className="text-sm font-medium text-zinc-100" numberOfLines={1}>
            {name}
          </Text>
          {isConnected ? (
            <View className="flex-row items-center gap-1 rounded-full bg-green-500/15 px-2 py-0.5">
              <AppIcon icon={Tick02Icon} size={10} color="#22c55e" />
              <Text className="text-[11px] font-medium text-green-500">
                Connected
              </Text>
            </View>
          ) : trailingLabel ? (
            <View className="rounded-full bg-zinc-700 px-2 py-0.5">
              <Text className="text-[11px] font-medium text-zinc-300">
                {trailingLabel}
              </Text>
            </View>
          ) : null}
        </View>
        {description ? (
          <Text className="mt-0.5 text-xs text-zinc-400" numberOfLines={2}>
            {description}
          </Text>
        ) : null}
      </View>

      {!isConnected && canConnect && onAction ? (
        <Pressable
          onPress={onAction}
          className="rounded-full bg-brand active:bg-brand/90 px-3 py-1.5 shrink-0"
        >
          <Text className="text-xs font-semibold text-brand-foreground">
            Connect
          </Text>
        </Pressable>
      ) : null}
    </Pressable>
  );
}

export function IntegrationListCard({
  data,
}: {
  data: IntegrationListCardData;
}) {
  const router = useRouter();
  const { integrations, connect } = useIntegrations();

  const connected: Integration[] = integrations
    .filter((i) => i.status === "connected")
    .sort((a, b) => a.name.localeCompare(b.name));
  const available: Integration[] = integrations
    .filter((i) => i.status !== "connected")
    .sort((a, b) => a.name.localeCompare(b.name));
  const suggested = data.suggested ?? [];

  const handleIntegrationPress = useCallback(
    (integrationId: string) => {
      router.push({
        pathname: "/(app)/(tabs)/integrations",
        params: { id: integrationId },
      });
    },
    [router],
  );

  const handleSuggestedPress = useCallback(
    (slug: string) => {
      router.push({
        pathname: "/(app)/(tabs)/integrations",
        params: { slug },
      });
    },
    [router],
  );

  const handleConnect = useCallback(
    (integrationId: string) => {
      void connect(integrationId);
    },
    [connect],
  );

  const totalCount = integrations.length;

  return (
    <ToolCardShell>
      <ToolCardHeader
        icon={ConnectIcon}
        iconColor="#00bbff"
        title="Integrations"
        count={totalCount}
      />

      {connected.length > 0 ? (
        <View className="mt-1 mb-3">
          <SectionLabel>Connected ({connected.length})</SectionLabel>
          <View className="gap-2">
            {connected.map((integration) => (
              <IntegrationRow
                key={integration.id}
                id={integration.id}
                name={integration.name}
                description={integration.description}
                iconUrl={integration.iconUrl}
                isConnected
                canConnect={false}
                onPress={() => handleIntegrationPress(integration.id)}
              />
            ))}
          </View>
        </View>
      ) : null}

      {suggested.length > 0 ? (
        <View className="mb-3">
          <SectionLabel>Discover more ({suggested.length})</SectionLabel>
          <View className="gap-2">
            {suggested.map((item) => (
              <IntegrationRow
                key={item.id}
                id={item.id}
                name={item.name}
                description={item.description}
                iconUrl={item.iconUrl}
                isConnected={false}
                canConnect={false}
                trailingLabel="Community"
                onPress={() => handleSuggestedPress(item.slug)}
              />
            ))}
          </View>
        </View>
      ) : null}

      {available.length > 0 ? (
        <View>
          <SectionLabel>Available ({available.length})</SectionLabel>
          <View className="gap-2">
            {available.map((integration) => {
              const canConnect =
                integration.source === "custom" ||
                integration.available !== false;
              return (
                <IntegrationRow
                  key={integration.id}
                  id={integration.id}
                  name={integration.name}
                  description={integration.description}
                  iconUrl={integration.iconUrl}
                  isConnected={false}
                  canConnect={canConnect}
                  onPress={() => handleIntegrationPress(integration.id)}
                  onAction={() => handleConnect(integration.id)}
                />
              );
            })}
          </View>
        </View>
      ) : null}
    </ToolCardShell>
  );
}
