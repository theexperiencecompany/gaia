import { useRouter } from "expo-router";
import { Card, Chip, Skeleton, SkeletonGroup } from "heroui-native";
import { useCallback, useMemo, useRef, useState } from "react";
import {
  Alert,
  FlatList,
  Pressable,
  RefreshControl,
  ScrollView,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import {
  AppIcon,
  ArrowLeft01Icon,
  ConnectIcon,
  PlusSignIcon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import { AppEmptyStateCard } from "@/shared/components/ui/app-empty-state-card";
import { AppFilterChipGroup } from "@/shared/components/ui/app-filter-chip-group";
import { AppSearchInput } from "@/shared/components/ui/app-search-input";
import { deleteCustomIntegration } from "../api/integrations-api";
import { getCategoryLabel, sortCategories } from "../constants/categories";
import { useIntegrations } from "../hooks/useIntegrations";
import type { Integration } from "../types";
import { BearerTokenSheet, type BearerTokenSheetRef } from "./BearerTokenSheet";
import { CommunityIntegrationsTab } from "./CommunityIntegrationsTab";
import {
  CreateMCPIntegrationSheet,
  type CreateMCPIntegrationSheetRef,
} from "./CreateMCPIntegrationSheet";
import { IntegrationRow } from "./IntegrationRow";
import {
  IntegrationDetailSheet,
  type IntegrationDetailSheetRef,
} from "./integration-detail-sheet";

type Tab = "all" | "community";

type ListItem =
  | { type: "section-header"; category: string; count: number }
  | { type: "integration"; integration: Integration };

function EmptyState({ query }: { query: string }) {
  const { spacing } = useResponsive();

  return (
    <View
      style={{
        paddingHorizontal: spacing.md,
        paddingVertical: spacing.xl * 2,
      }}
    >
      <AppEmptyStateCard
        title={query ? `No results for "${query}"` : "No integrations found"}
        description={
          query ? "Try a different search term." : "Check back later."
        }
        icon={<AppIcon icon={ConnectIcon} size={40} color="#3a3a3c" />}
        className="rounded-2xl bg-zinc-800/30"
        bodyClassName="px-6 py-10"
      />
    </View>
  );
}

function LoadingState() {
  const { spacing } = useResponsive();

  return (
    <View
      style={{
        paddingHorizontal: spacing.md,
        paddingVertical: spacing.xl * 2,
      }}
    >
      <SkeletonGroup>
        <Card
          variant="secondary"
          animation="disable-all"
          className="rounded-2xl"
        >
          <Card.Body className="items-center gap-4 px-6 py-10">
            <Skeleton className="h-4 w-40 rounded-xl" />
            <Skeleton className="h-4 w-56 rounded-xl" />
            <Skeleton className="h-4 w-32 rounded-xl" />
          </Card.Body>
        </Card>
      </SkeletonGroup>
    </View>
  );
}

export function IntegrationsScreen() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { spacing, fontSize } = useResponsive();

  const detailSheetRef = useRef<IntegrationDetailSheetRef>(null);
  const createSheetRef = useRef<CreateMCPIntegrationSheetRef>(null);
  const bearerSheetRef = useRef<BearerTokenSheetRef>(null);

  const { integrations, isLoading, refetch, connect, disconnect } =
    useIntegrations();

  const [tab, setTab] = useState<Tab>("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedCategory, setSelectedCategory] = useState("all");
  const [pendingId, setPendingId] = useState<string | null>(null);
  const [isRefreshing, setIsRefreshing] = useState(false);

  const availableCategories = useMemo(
    () =>
      sortCategories(
        Array.from(new Set(integrations.map((item) => item.category))),
      ),
    [integrations],
  );

  const categoryOptions = useMemo(
    () => [
      { key: "all", label: "All" },
      ...availableCategories.map((category) => ({
        key: category,
        label: getCategoryLabel(category),
      })),
    ],
    [availableCategories],
  );

  const filteredIntegrations = useMemo(() => {
    let results = integrations;

    if (selectedCategory !== "all") {
      results = results.filter(
        (integration) => integration.category === selectedCategory,
      );
    }

    const normalisedQuery = searchQuery.trim().toLowerCase();
    if (normalisedQuery) {
      results = results.filter(
        (integration) =>
          integration.name.toLowerCase().includes(normalisedQuery) ||
          integration.description.toLowerCase().includes(normalisedQuery),
      );
    }

    return results;
  }, [integrations, searchQuery, selectedCategory]);

  const connectedCount = useMemo(
    () =>
      integrations.filter((integration) => integration.status === "connected")
        .length,
    [integrations],
  );

  const listItems = useMemo<ListItem[]>(() => {
    if (selectedCategory !== "all") {
      return filteredIntegrations.map((integration) => ({
        type: "integration" as const,
        integration,
      }));
    }

    const grouped: Record<string, Integration[]> = {};
    for (const integration of filteredIntegrations) {
      grouped[integration.category] ??= [];
      grouped[integration.category].push(integration);
    }

    const items: ListItem[] = [];
    const orderedCategories = availableCategories.filter(
      (category) => grouped[category]?.length,
    );

    for (const category of orderedCategories) {
      items.push({
        type: "section-header",
        category,
        count: grouped[category].length,
      });

      for (const integration of grouped[category]) {
        items.push({ type: "integration", integration });
      }
    }

    return items;
  }, [availableCategories, filteredIntegrations, selectedCategory]);

  const handleSearchChange = useCallback(
    (text: string) => {
      setSearchQuery(text);
      if (text && selectedCategory !== "all") {
        setSelectedCategory("all");
      }
    },
    [selectedCategory],
  );

  const handleConnect = useCallback(
    async (integration: Integration) => {
      const authType = integration.authType ?? "oauth";
      if (authType === "bearer") {
        bearerSheetRef.current?.open({
          integrationId: integration.id,
          integrationName: integration.name,
          iconUrl: integration.iconUrl,
        });
        return;
      }

      setPendingId(integration.id);
      const result = await connect(integration.id);
      setPendingId(null);

      if (!result.success && !result.cancelled) {
        Alert.alert("Error", result.error ?? "Failed to connect integration.");
      }
    },
    [connect],
  );

  const handleDisconnect = useCallback(
    async (integration: Integration) => {
      setPendingId(integration.id);
      const success = await disconnect(integration.id);
      setPendingId(null);
      if (!success) {
        Alert.alert("Error", "Failed to disconnect integration.");
      }
    },
    [disconnect],
  );

  const handleRowAction = useCallback(
    (integration: Integration) => {
      if (pendingId) return;
      if (integration.status === "connected") {
        Alert.alert(
          "Disconnect Integration",
          `Disconnect ${integration.name}?`,
          [
            { text: "Cancel", style: "cancel" },
            {
              text: "Disconnect",
              style: "destructive",
              onPress: () => {
                void handleDisconnect(integration);
              },
            },
          ],
        );
      } else {
        void handleConnect(integration);
      }
    },
    [pendingId, handleConnect, handleDisconnect],
  );

  const openDetailSheet = useCallback((integration: Integration) => {
    detailSheetRef.current?.open(integration);
  }, []);

  const handleEdit = useCallback((integration: Integration) => {
    createSheetRef.current?.open(integration);
  }, []);

  const handleDelete = useCallback(
    async (integration: Integration) => {
      try {
        await deleteCustomIntegration(integration.id);
        refetch();
      } catch {
        Alert.alert("Error", "Failed to delete integration.");
      }
    },
    [refetch],
  );

  const handleRefresh = useCallback(async () => {
    setIsRefreshing(true);
    refetch();
    setIsRefreshing(false);
  }, [refetch]);

  const keyExtractor = useCallback((item: ListItem) => {
    if (item.type === "section-header") return `header-${item.category}`;
    return `integration-${item.integration.id}`;
  }, []);

  const renderItem = useCallback(
    ({ item }: { item: ListItem }) => {
      if (item.type === "section-header") {
        return (
          <View
            style={{
              flexDirection: "row",
              alignItems: "center",
              gap: 8,
              paddingHorizontal: spacing.md,
              paddingTop: spacing.lg,
              paddingBottom: spacing.sm,
            }}
          >
            <Text
              className="text-zinc-100"
              style={{ fontSize: fontSize.sm, fontWeight: "600" }}
            >
              {getCategoryLabel(item.category)}
            </Text>
            <Text className="text-zinc-500" style={{ fontSize: fontSize.xs }}>
              {item.count}
            </Text>
          </View>
        );
      }

      return (
        <View
          style={{
            paddingHorizontal: spacing.md,
            marginBottom: spacing.sm,
          }}
        >
          <IntegrationRow
            integration={item.integration}
            isPending={pendingId === item.integration.id}
            onPressRow={openDetailSheet}
            onPressAction={handleRowAction}
          />
        </View>
      );
    },
    [
      pendingId,
      openDetailSheet,
      handleRowAction,
      spacing.md,
      spacing.sm,
      spacing.lg,
      fontSize.sm,
      fontSize.xs,
    ],
  );

  const ListHeader = useCallback(
    () => (
      <View style={{ gap: spacing.md, paddingBottom: spacing.md }}>
        <View style={{ paddingHorizontal: spacing.md }}>
          <Card
            variant="secondary"
            animation="disable-all"
            className="rounded-2xl"
          >
            <Card.Body className="flex-row items-center justify-between px-4 py-3">
              <Text className="text-zinc-300" style={{ fontSize: fontSize.xs }}>
                {connectedCount} of {integrations.length} connected
              </Text>
              {selectedCategory !== "all" ? (
                <Chip
                  size="sm"
                  variant="soft"
                  color="accent"
                  animation="disable-all"
                >
                  <Chip.Label>{getCategoryLabel(selectedCategory)}</Chip.Label>
                </Chip>
              ) : null}
            </Card.Body>
          </Card>
        </View>

        {availableCategories.length > 0 ? (
          <ScrollView
            horizontal
            showsHorizontalScrollIndicator={false}
            contentContainerStyle={{ paddingHorizontal: spacing.md }}
          >
            <AppFilterChipGroup
              options={categoryOptions}
              selectedKey={selectedCategory}
              onSelect={(category) => {
                setSelectedCategory(category ?? "all");
              }}
              className="flex-nowrap gap-2"
              selectedVariant="primary"
              unselectedVariant="tertiary"
              chipClassName="bg-white/10"
            />
          </ScrollView>
        ) : null}
      </View>
    ),
    [
      availableCategories.length,
      categoryOptions,
      connectedCount,
      fontSize.xs,
      integrations.length,
      selectedCategory,
      spacing.md,
    ],
  );

  return (
    <View className="flex-1 bg-[#111111]">
      <View
        style={{
          paddingTop: insets.top + spacing.sm,
          paddingBottom: spacing.md,
          borderBottomWidth: 1,
          borderBottomColor: "rgba(255,255,255,0.08)",
          gap: spacing.md,
        }}
      >
        <View
          style={{
            paddingHorizontal: spacing.md,
            flexDirection: "row",
            alignItems: "center",
            gap: spacing.sm,
          }}
        >
          {router.canGoBack() ? (
            <Pressable
              onPress={() => router.back()}
              hitSlop={8}
              className="h-9 w-9 items-center justify-center rounded-full active:bg-white/[0.06]"
              accessibilityRole="button"
              accessibilityLabel="Go back"
            >
              <AppIcon icon={ArrowLeft01Icon} size={18} color="#fff" />
            </Pressable>
          ) : null}

          <Text
            className="flex-1 text-white"
            style={{ fontSize: fontSize.base, fontWeight: "600" }}
          >
            Integrations
          </Text>

          <Pressable
            onPress={() => createSheetRef.current?.open()}
            hitSlop={6}
            className="flex-row items-center gap-1 rounded-full bg-primary px-3 py-1.5"
            accessibilityRole="button"
            accessibilityLabel="Add MCP integration"
          >
            <AppIcon icon={PlusSignIcon} size={14} color="#000" />
            <Text
              style={{
                color: "#000",
                fontSize: fontSize.xs,
                fontWeight: "600",
              }}
            >
              Add MCP
            </Text>
          </Pressable>
        </View>

        <View style={{ paddingHorizontal: spacing.md }}>
          <AppSearchInput
            value={searchQuery}
            onChangeText={handleSearchChange}
            placeholder="Search integrations"
            className="gap-0"
            inputClassName="bg-white/5"
          />
        </View>

        <View
          style={{
            paddingHorizontal: spacing.md,
            flexDirection: "row",
            gap: spacing.sm,
          }}
        >
          <Chip
            size="sm"
            variant={tab === "all" ? "primary" : "tertiary"}
            color={tab === "all" ? "accent" : "default"}
            onPress={() => setTab("all")}
            animation="disable-all"
            className={tab === "all" ? undefined : "bg-white/10"}
          >
            <Chip.Label>All</Chip.Label>
          </Chip>
          <Chip
            size="sm"
            variant={tab === "community" ? "primary" : "tertiary"}
            color={tab === "community" ? "accent" : "default"}
            onPress={() => setTab("community")}
            animation="disable-all"
            className={tab === "community" ? undefined : "bg-white/10"}
          >
            <Chip.Label>Community</Chip.Label>
          </Chip>
        </View>
      </View>

      {tab === "community" ? (
        <CommunityIntegrationsTab />
      ) : (
        <FlatList
          data={listItems}
          keyExtractor={keyExtractor}
          renderItem={renderItem}
          ListHeaderComponent={ListHeader}
          ListEmptyComponent={
            isLoading ? <LoadingState /> : <EmptyState query={searchQuery} />
          }
          contentContainerStyle={{
            paddingTop: spacing.md,
            paddingBottom: insets.bottom + spacing.xl,
            flexGrow: 1,
          }}
          refreshControl={
            <RefreshControl
              refreshing={isRefreshing}
              onRefresh={() => void handleRefresh()}
              tintColor="#00bbff"
            />
          }
          showsVerticalScrollIndicator={false}
          keyboardShouldPersistTaps="handled"
          keyboardDismissMode="on-drag"
        />
      )}

      <IntegrationDetailSheet
        ref={detailSheetRef}
        onConnect={handleConnect}
        onDisconnect={handleDisconnect}
        onEdit={handleEdit}
        onDelete={handleDelete}
      />

      <CreateMCPIntegrationSheet
        ref={createSheetRef}
        onIntegrationCreated={() => refetch()}
        onIntegrationUpdated={() => refetch()}
      />

      <BearerTokenSheet ref={bearerSheetRef} onSuccess={() => refetch()} />
    </View>
  );
}
