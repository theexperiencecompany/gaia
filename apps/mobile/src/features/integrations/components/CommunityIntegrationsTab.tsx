import { Skeleton, SkeletonGroup } from "heroui-native";
import { useCallback, useState } from "react";
import { FlatList, Pressable, ScrollView, View } from "react-native";
import { AppIcon, ConnectIcon } from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import { AppEmptyStateCard } from "@/shared/components/ui/app-empty-state-card";
import { useCommunityIntegrations } from "../hooks/useCommunityIntegrations";
import type { CommunityIntegration } from "../types";
import { CommunityIntegrationCard } from "./CommunityIntegrationCard";

const CATEGORY_FILTERS: { key: string; label: string }[] = [
  { key: "all", label: "All" },
  { key: "productivity", label: "Productivity" },
  { key: "communication", label: "Communication" },
  { key: "developer", label: "Developer" },
  { key: "analytics", label: "Analytics" },
  { key: "finance", label: "Finance" },
  { key: "ai/ml", label: "AI/ML" },
  { key: "education", label: "Education" },
  { key: "personal", label: "Personal" },
];

interface CommunityIntegrationsTabProps {
  search?: string;
  onIntegrationPress?: (integration: CommunityIntegration) => void;
}

function CardSkeleton() {
  return (
    <View
      style={{
        padding: 16,
        borderRadius: 24,
        backgroundColor: "#27272a",
        gap: 12,
      }}
    >
      <View style={{ flexDirection: "row", alignItems: "center", gap: 12 }}>
        <Skeleton style={{ width: 40, height: 40, borderRadius: 12 }} />
        <View style={{ flex: 1, gap: 6 }}>
          <Skeleton style={{ height: 14, width: "60%", borderRadius: 8 }} />
          <Skeleton style={{ height: 10, width: "30%", borderRadius: 8 }} />
        </View>
        <Skeleton style={{ width: 56, height: 32, borderRadius: 999 }} />
      </View>
      <View style={{ gap: 6 }}>
        <Skeleton style={{ height: 12, width: "100%", borderRadius: 8 }} />
        <Skeleton style={{ height: 12, width: "85%", borderRadius: 8 }} />
      </View>
      <View
        style={{
          flexDirection: "row",
          justifyContent: "space-between",
          alignItems: "center",
        }}
      >
        <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
          <Skeleton style={{ width: 20, height: 20, borderRadius: 999 }} />
          <Skeleton style={{ height: 10, width: 80, borderRadius: 8 }} />
        </View>
        <Skeleton style={{ height: 10, width: 60, borderRadius: 8 }} />
      </View>
    </View>
  );
}

export function CommunityIntegrationsTab({
  search,
  onIntegrationPress,
}: CommunityIntegrationsTabProps) {
  const { spacing, fontSize } = useResponsive();
  const [selectedCategory, setSelectedCategory] = useState("all");

  const categoryParam =
    selectedCategory === "all" ? undefined : selectedCategory;
  const searchParam = search?.trim() || undefined;

  const {
    integrations,
    total,
    isLoading,
    isFetchingNextPage,
    hasNextPage,
    fetchNextPage,
    error,
  } = useCommunityIntegrations({
    search: searchParam,
    category: categoryParam,
    sort: "popular",
  });

  const handleLoadMore = useCallback(() => {
    if (hasNextPage && !isFetchingNextPage) {
      fetchNextPage();
    }
  }, [hasNextPage, isFetchingNextPage, fetchNextPage]);

  const renderItem = useCallback(
    ({ item }: { item: CommunityIntegration }) => (
      <View style={{ paddingHorizontal: spacing.md, paddingTop: spacing.sm }}>
        <CommunityIntegrationCard
          integration={item}
          onPress={onIntegrationPress}
        />
      </View>
    ),
    [onIntegrationPress, spacing.md, spacing.sm],
  );

  const keyExtractor = useCallback(
    (item: CommunityIntegration) => item.integrationId,
    [],
  );

  const ListHeader = useCallback(
    () => (
      <View>
        <ScrollView
          horizontal
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={{
            paddingHorizontal: spacing.md,
            paddingTop: spacing.sm,
            gap: 8,
            alignItems: "center",
          }}
        >
          {CATEGORY_FILTERS.map((option) => {
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

        <View
          style={{
            paddingHorizontal: spacing.md,
            paddingTop: spacing.md,
            paddingBottom: spacing.xs,
            flexDirection: "row",
            alignItems: "center",
            justifyContent: "space-between",
          }}
        >
          <Text
            className="text-zinc-100"
            style={{ fontSize: fontSize.base, fontWeight: "600" }}
          >
            Community
          </Text>
          {total > 0 ? (
            <View
              className="rounded-full bg-white/[0.06]"
              style={{
                paddingHorizontal: 10,
                paddingVertical: 2,
                minWidth: 24,
                alignItems: "center",
              }}
            >
              <Text
                className="text-zinc-400"
                style={{ fontSize: fontSize.xs - 1, fontWeight: "600" }}
              >
                {total}
              </Text>
            </View>
          ) : null}
        </View>
      </View>
    ),
    [
      selectedCategory,
      total,
      spacing.md,
      spacing.sm,
      spacing.xs,
      fontSize.base,
      fontSize.xs,
    ],
  );

  const ListEmpty = useCallback(() => {
    if (isLoading) {
      return (
        <SkeletonGroup>
          <View style={{ paddingHorizontal: spacing.md, gap: spacing.sm }}>
            {Array.from({ length: 4 }).map((_, index) => (
              // biome-ignore lint/suspicious/noArrayIndexKey: static skeleton placeholders
              <CardSkeleton key={index} />
            ))}
          </View>
        </SkeletonGroup>
      );
    }

    if (error) {
      return (
        <View style={{ paddingHorizontal: spacing.md, paddingTop: spacing.lg }}>
          <AppEmptyStateCard
            title="Couldn't load community integrations"
            description="Pull down to refresh, or try again in a moment."
            icon={<AppIcon icon={ConnectIcon} size={36} color="#3a3a3c" />}
            className="rounded-2xl bg-zinc-800/30"
            bodyClassName="px-6 py-10"
          />
        </View>
      );
    }

    return (
      <View style={{ paddingHorizontal: spacing.md, paddingTop: spacing.lg }}>
        <AppEmptyStateCard
          title={
            searchParam ? `No results for "${searchParam}"` : "No integrations"
          }
          description={
            searchParam
              ? "Try a different search term or category."
              : "Check back later for new community integrations."
          }
          icon={<AppIcon icon={ConnectIcon} size={36} color="#3a3a3c" />}
          className="rounded-2xl bg-zinc-800/30"
          bodyClassName="px-6 py-10"
        />
      </View>
    );
  }, [isLoading, error, searchParam, spacing.md, spacing.sm, spacing.lg]);

  const ListFooter = useCallback(() => {
    if (!isFetchingNextPage) return null;
    return (
      <View
        style={{
          paddingHorizontal: spacing.md,
          paddingTop: spacing.sm,
        }}
      >
        <SkeletonGroup>
          <CardSkeleton />
        </SkeletonGroup>
      </View>
    );
  }, [isFetchingNextPage, spacing.md, spacing.sm]);

  return (
    <FlatList
      data={integrations}
      keyExtractor={keyExtractor}
      renderItem={renderItem}
      ListHeaderComponent={ListHeader}
      ListEmptyComponent={ListEmpty}
      ListFooterComponent={ListFooter}
      onEndReached={handleLoadMore}
      onEndReachedThreshold={0.3}
      contentContainerStyle={{ paddingBottom: spacing.xl }}
      showsVerticalScrollIndicator={false}
      keyboardShouldPersistTaps="handled"
      keyboardDismissMode="on-drag"
    />
  );
}
