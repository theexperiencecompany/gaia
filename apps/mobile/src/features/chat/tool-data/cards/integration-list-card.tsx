import { useRouter } from "expo-router";
import { Button, Chip } from "heroui-native";
import { useCallback, useMemo, useRef, useState } from "react";
import { Pressable, ScrollView, View } from "react-native";
import {
  ArrowRight02Icon,
  ConnectIcon,
  InformationCircleIcon,
} from "@/components/icons";
import { AppIcon } from "@/components/icons/app-icon";
import { Text } from "@/components/ui/text";
import {
  CollapsibleCard,
  ToolCardInner,
} from "@/features/chat/tool-data/primitives";
import { getToolCategoryIcon } from "@/features/chat/utils/tool-icons";
import { addPublicIntegration } from "@/features/integrations/api/integrations-api";
import {
  BearerTokenSheet,
  type BearerTokenSheetRef,
} from "@/features/integrations/components/BearerTokenSheet";
import { useIntegrations } from "@/features/integrations/hooks/useIntegrations";
import type { Integration } from "@/features/integrations/types";

// Mirrors web SuggestedIntegration (apps/web/src/features/integrations/types).
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

// Same payload shape as web IntegrationListStreamData, plus optional
// `integrations` echo that the mobile renderer may merge in.
export interface IntegrationListData {
  hasSuggestions?: boolean;
  message?: string;
  suggested?: SuggestedIntegration[];
  integrations?: SuggestedIntegration[];
}

interface IntegrationListCardProps {
  data: IntegrationListData;
  /** Optional override — defaults to useIntegrations().connect */
  onConnect?: (integrationId: string) => Promise<unknown> | undefined;
  /** Optional override — defaults to useIntegrations().disconnect */
  onDisconnect?: (integrationId: string) => Promise<unknown> | undefined;
}

// ---------------------------------------------------------------------------
// SectionHeader — mirrors web AccordionTitle (title + count chip + info icon)
// ---------------------------------------------------------------------------

interface SectionHeaderProps {
  title: string;
  count: number;
}

function SectionHeader({ title, count }: SectionHeaderProps) {
  return (
    <View className="flex-row items-center gap-2 px-3 pt-3 pb-2">
      <Text className="text-zinc-400 text-xs font-semibold">{title}</Text>
      <Chip size="sm" variant="soft" color="default" animation="disable-all">
        <Chip.Label>{String(count)}</Chip.Label>
      </Chip>
      <View className="flex-1" />
      <AppIcon icon={InformationCircleIcon} size={14} color="#71717a" />
    </View>
  );
}

// ---------------------------------------------------------------------------
// IntegrationRow — connected/available rows. Mirrors web renderIntegration.
// ---------------------------------------------------------------------------

interface IntegrationRowProps {
  integration: Integration;
  onConnect: () => void;
}

function IntegrationRow({ integration, onConnect }: IntegrationRowProps) {
  const isConnected = integration.status === "connected";
  const isAvailable =
    integration.source === "custom" || !!integration.available;

  return (
    <ToolCardInner dense>
      <View className="flex-row items-start gap-3">
        <View className="shrink-0 pt-0.5">
          {getToolCategoryIcon(
            integration.id,
            { size: 20, showBackground: false },
            integration.iconUrl,
          )}
        </View>

        <View className="min-w-0 flex-1">
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
            ) : null}
          </View>
          {integration.description ? (
            <Text className="text-zinc-400 text-xs mt-1" numberOfLines={2}>
              {integration.description}
            </Text>
          ) : null}
        </View>

        {!isConnected && isAvailable ? (
          <Button size="sm" variant="primary" onPress={onConnect}>
            <Button.Label>Connect</Button.Label>
          </Button>
        ) : null}
      </View>
    </ToolCardInner>
  );
}

// ---------------------------------------------------------------------------
// SuggestedRow — discover-more rows. Mirrors web renderSuggested.
// ---------------------------------------------------------------------------

interface SuggestedRowProps {
  suggestion: SuggestedIntegration;
  isAdding: boolean;
  onAdd: () => void;
}

function SuggestedRow({ suggestion, isAdding, onAdd }: SuggestedRowProps) {
  return (
    <ToolCardInner dense>
      <View className="flex-row items-start gap-3">
        <View className="shrink-0 pt-0.5">
          {getToolCategoryIcon(
            suggestion.id,
            { size: 20, showBackground: false },
            suggestion.iconUrl,
          )}
        </View>

        <View className="min-w-0 flex-1">
          <View className="flex-row items-center gap-2 flex-wrap">
            <Text className="text-zinc-100 text-sm font-medium">
              {suggestion.name}
            </Text>
            <Chip
              size="sm"
              variant="soft"
              color="accent"
              animation="disable-all"
            >
              <Chip.Label>Community</Chip.Label>
            </Chip>
          </View>
          <Text className="text-zinc-400 text-xs mt-1" numberOfLines={2}>
            {suggestion.description}
          </Text>
        </View>

        <Button
          size="sm"
          variant="primary"
          isDisabled={isAdding}
          onPress={onAdd}
        >
          <Button.Label>{isAdding ? "Adding..." : "Add"}</Button.Label>
        </Button>
      </View>
    </ToolCardInner>
  );
}

// ---------------------------------------------------------------------------
// Card
// ---------------------------------------------------------------------------

export function IntegrationListCard({
  data,
  onConnect,
  onDisconnect: _onDisconnect,
}: IntegrationListCardProps) {
  const router = useRouter();
  const { integrations, connect, refetch } = useIntegrations();
  const bearerSheetRef = useRef<BearerTokenSheetRef>(null);
  const [addingIds, setAddingIds] = useState<Set<string>>(new Set());

  const suggestedIntegrations = useMemo<SuggestedIntegration[]>(
    () => data.suggested ?? [],
    [data.suggested],
  );

  const connectedIntegrations = useMemo(
    () =>
      integrations
        .filter((i) => i.status === "connected")
        .toSorted((a, b) => a.name.localeCompare(b.name)),
    [integrations],
  );

  const notConnectedIntegrations = useMemo(
    () =>
      integrations
        .filter((i) => i.status !== "connected")
        .toSorted((a, b) => a.name.localeCompare(b.name)),
    [integrations],
  );

  const handleConnect = useCallback(
    async (integration: Integration) => {
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
    },
    [connect, onConnect],
  );

  const handleAddSuggested = useCallback(
    async (suggestion: SuggestedIntegration) => {
      setAddingIds((prev) => new Set(prev).add(suggestion.id));
      try {
        const result = await addPublicIntegration(suggestion.slug);
        if (result.status === "connected" || result.status === "created") {
          refetch();
        }
      } catch (error) {
        console.error("Failed to add suggested integration:", error);
      } finally {
        setAddingIds((prev) => {
          const next = new Set(prev);
          next.delete(suggestion.id);
          return next;
        });
      }
    },
    [refetch],
  );

  const total =
    integrations.length +
    (data.hasSuggestions ? suggestedIntegrations.length : 0);

  return (
    <>
      <CollapsibleCard
        icon={ConnectIcon}
        iconSize={20}
        title={(open) =>
          `${open ? "Hide" : "Show"} ${total} Integration${total === 1 ? "" : "s"}`
        }
        titleTone="muted"
      >
        <View className="gap-2">
          {data.message ? (
            <Text className="text-zinc-300 text-sm px-1 mb-1">
              {data.message}
            </Text>
          ) : null}

          {connectedIntegrations.length > 0 ? (
            <View className="rounded-2xl bg-zinc-900">
              <SectionHeader
                title="Connected"
                count={connectedIntegrations.length}
              />
              <ScrollView
                style={{ maxHeight: 240 }}
                showsVerticalScrollIndicator={false}
              >
                <View className="px-3 pb-3 gap-2">
                  {connectedIntegrations.map((i) => (
                    <IntegrationRow
                      key={i.id}
                      integration={i}
                      onConnect={() => {
                        void handleConnect(i);
                      }}
                    />
                  ))}
                </View>
              </ScrollView>
            </View>
          ) : null}

          {suggestedIntegrations.length > 0 ? (
            <View className="rounded-2xl bg-zinc-900">
              <SectionHeader
                title="Discover More"
                count={suggestedIntegrations.length}
              />
              <ScrollView
                style={{ maxHeight: 240 }}
                showsVerticalScrollIndicator={false}
              >
                <View className="px-3 gap-2">
                  {suggestedIntegrations.map((s) => (
                    <SuggestedRow
                      key={s.id}
                      suggestion={s}
                      isAdding={addingIds.has(s.id)}
                      onAdd={() => {
                        void handleAddSuggested(s);
                      }}
                    />
                  ))}
                </View>
              </ScrollView>
              <Pressable
                onPress={() => {
                  // Web links to /marketplace; mobile routes to the
                  // integrations tab where the marketplace lives.
                  router.push("/(app)/integrations");
                }}
                android_ripple={{ color: "rgba(255,255,255,0.05)" }}
                className="flex-row items-center justify-center gap-1 py-3"
              >
                <Text className="text-primary text-xs font-medium">
                  Go to Marketplace
                </Text>
                <AppIcon icon={ArrowRight02Icon} size={14} color="#00bbff" />
              </Pressable>
            </View>
          ) : null}

          {notConnectedIntegrations.length > 0 ? (
            <View className="rounded-2xl bg-zinc-900">
              <SectionHeader
                title="Available"
                count={notConnectedIntegrations.length}
              />
              <ScrollView
                style={{ maxHeight: 320 }}
                showsVerticalScrollIndicator={false}
              >
                <View className="px-3 pb-3 gap-2">
                  {notConnectedIntegrations.map((i) => (
                    <IntegrationRow
                      key={i.id}
                      integration={i}
                      onConnect={() => {
                        void handleConnect(i);
                      }}
                    />
                  ))}
                </View>
              </ScrollView>
            </View>
          ) : null}

          {connectedIntegrations.length === 0 &&
          suggestedIntegrations.length === 0 &&
          notConnectedIntegrations.length === 0 ? (
            <ToolCardInner>
              <Text className="text-zinc-500 text-sm text-center py-2">
                No integrations available
              </Text>
            </ToolCardInner>
          ) : null}
        </View>
      </CollapsibleCard>

      <BearerTokenSheet ref={bearerSheetRef} />
    </>
  );
}
