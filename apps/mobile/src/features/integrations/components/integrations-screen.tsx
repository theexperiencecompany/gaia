import { useNavigation } from "expo-router";
import { Skeleton, SkeletonGroup } from "heroui-native";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Alert,
  BackHandler,
  FlatList,
  Pressable,
  RefreshControl,
  ScrollView,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import {
  AppIcon,
  ArrowRight01Icon,
  ConnectIcon,
  PlusSignIcon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import { SidebarMenuButton } from "@/shared/components/sidebar-menu-button";
import { AppEmptyStateCard } from "@/shared/components/ui/app-empty-state-card";
import { AppSearchInput } from "@/shared/components/ui/app-search-input";
import { BackButton } from "@/shared/components/ui/back-button";
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
    <SkeletonGroup>
      <View
        style={{
          paddingHorizontal: spacing.md,
          paddingTop: spacing.md,
          gap: spacing.sm + 2,
        }}
      >
        {Array.from({ length: 6 }).map((_, index) => (
          <View
            // biome-ignore lint/suspicious/noArrayIndexKey: static skeleton placeholders
            key={index}
            style={{
              flexDirection: "row",
              alignItems: "center",
              paddingHorizontal: spacing.md,
              paddingVertical: spacing.sm + 2,
              gap: spacing.sm + 4,
            }}
          >
            <Skeleton className="h-10 w-10 rounded-full" />
            <View style={{ flex: 1, gap: 6 }}>
              <Skeleton className="h-3.5 w-32 rounded-xl" />
              <Skeleton className="h-3 w-48 rounded-xl" />
            </View>
            <Skeleton className="h-7 w-20 rounded-full" />
          </View>
        ))}
      </View>
    </SkeletonGroup>
  );
}

export function IntegrationsScreen() {
  const insets = useSafeAreaInsets();
  const { spacing, fontSize } = useResponsive();
  const navigation = useNavigation();

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

  // Treat the community sub-view as a virtual back-stack entry: while it's
  // active, disable the iOS swipe-back gesture and intercept Android's
  // hardware back so they pop the tab state instead of the whole screen.
  useEffect(() => {
    navigation.setOptions({ gestureEnabled: tab !== "community" });
  }, [navigation, tab]);

  useEffect(() => {
    if (tab !== "community") return;
    const sub = BackHandler.addEventListener("hardwareBackPress", () => {
      setTab("all");
      return true;
    });
    return () => sub.remove();
  }, [tab]);

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
      if (pendingId) return;
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
    [connect, pendingId],
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
              gap: 10,
              paddingHorizontal: spacing.md,
              paddingTop: spacing.lg,
              paddingBottom: spacing.sm,
            }}
          >
            <Text
              className="text-zinc-100"
              style={{ fontSize: fontSize.base, fontWeight: "600" }}
            >
              {getCategoryLabel(item.category)}
            </Text>
            <View
              className="rounded-full bg-white/[0.06] px-2 py-0.5"
              style={{ minWidth: 22, alignItems: "center" }}
            >
              <Text
                className="text-zinc-400"
                style={{ fontSize: fontSize.xs - 1, fontWeight: "600" }}
              >
                {item.count}
              </Text>
            </View>
          </View>
        );
      }

      return (
        <View style={{ paddingHorizontal: spacing.sm }}>
          <IntegrationRow
            integration={item.integration}
            isPending={pendingId === item.integration.id}
            onPressRow={openDetailSheet}
            onPressConnect={handleConnect}
          />
        </View>
      );
    },
    [
      pendingId,
      openDetailSheet,
      handleConnect,
      spacing.sm,
      spacing.md,
      spacing.lg,
      fontSize.base,
      fontSize.xs,
    ],
  );

  const ListHeader = useCallback(
    () => (
      <View style={{ paddingBottom: spacing.md, gap: spacing.md }}>
        {/* Marketplace banner — mirrors web's "Explore the Marketplace" card */}
        <View
          style={{
            marginHorizontal: spacing.md,
            backgroundColor: "rgba(255,255,255,0.04)",
            borderRadius: 16,
            paddingVertical: spacing.md,
            paddingHorizontal: spacing.md,
            flexDirection: "row",
            alignItems: "center",
            gap: spacing.sm,
          }}
        >
          <View style={{ flex: 1, gap: 2 }}>
            <Text
              style={{
                fontSize: fontSize.sm,
                fontWeight: "600",
                color: "#f4f4f5",
              }}
            >
              Explore the Marketplace
            </Text>
            <Text
              style={{
                fontSize: fontSize.xs,
                color: "#a1a1aa",
              }}
              numberOfLines={2}
            >
              Discover community integrations
            </Text>
          </View>
          <Pressable
            onPress={() => setTab("community")}
            accessibilityRole="button"
            accessibilityLabel="Browse marketplace"
            style={({ pressed }) => ({
              paddingHorizontal: 16,
              height: 40,
              borderRadius: 999,
              flexDirection: "row",
              alignItems: "center",
              gap: 6,
              backgroundColor: pressed ? "#0099d4" : "#00bbff",
            })}
          >
            <Text
              style={{
                fontSize: fontSize.sm,
                fontWeight: "600",
                color: "#000",
              }}
            >
              Browse
            </Text>
            <AppIcon icon={ArrowRight01Icon} size={14} color="#000" />
          </Pressable>
        </View>

        {availableCategories.length > 0 ? (
          <ScrollView
            horizontal
            showsHorizontalScrollIndicator={false}
            contentContainerStyle={{
              paddingHorizontal: spacing.md,
              gap: 8,
              alignItems: "center",
            }}
          >
            {categoryOptions.map((option) => {
              const isActive = option.key === selectedCategory;
              return (
                <Pressable
                  key={option.key}
                  onPress={() => setSelectedCategory(option.key)}
                  accessibilityRole="button"
                  accessibilityState={{ selected: isActive }}
                  style={({ pressed }) => ({
                    paddingHorizontal: 14,
                    height: 32,
                    borderRadius: 999,
                    alignItems: "center",
                    justifyContent: "center",
                    backgroundColor: isActive
                      ? pressed
                        ? "#0099d4"
                        : "#00bbff"
                      : pressed
                        ? "rgba(63,63,70,0.6)"
                        : "rgba(63,63,70,0.4)",
                  })}
                >
                  <Text
                    style={{
                      fontSize: fontSize.xs,
                      fontWeight: "600",
                      color: isActive ? "#000000" : "#d4d4d8",
                    }}
                  >
                    {option.label}
                  </Text>
                </Pressable>
              );
            })}
          </ScrollView>
        ) : null}
      </View>
    ),
    [
      availableCategories.length,
      categoryOptions,
      selectedCategory,
      spacing.md,
      spacing.sm,
      fontSize.sm,
      fontSize.xs,
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
          {tab === "community" ? (
            <BackButton onPress={() => setTab("all")} />
          ) : (
            <SidebarMenuButton />
          )}

          <Text
            className="flex-1 text-white"
            style={{ fontSize: fontSize.base, fontWeight: "600" }}
          >
            Integrations
          </Text>

          <Pressable
            onPress={() => createSheetRef.current?.open()}
            hitSlop={8}
            className="h-9 w-9 items-center justify-center rounded-full bg-primary/15 active:bg-primary/25"
            accessibilityRole="button"
            accessibilityLabel="Add custom integration"
          >
            <AppIcon icon={PlusSignIcon} size={18} color="#00bbff" />
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
      </View>

      {tab === "community" ? (
        <CommunityIntegrationsTab search={searchQuery} />
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
