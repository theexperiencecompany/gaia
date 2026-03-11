import { Chip, Skeleton, SkeletonGroup } from "heroui-native";
import { useCallback, useState } from "react";
import { FlatList, ScrollView, View } from "react-native";
import { Text } from "@/components/ui/text";
import { AppSearchInput } from "@/shared/components/ui";
import { useCommunityIntegrations } from "../hooks/useCommunityIntegrations";
import type { CommunityIntegration } from "../types";
import { CommunityIntegrationCard } from "./CommunityIntegrationCard";

const CATEGORY_FILTERS = [
  "All",
  "Productivity",
  "Communication",
  "Developer",
  "Analytics",
  "Finance",
  "AI/ML",
  "Education",
  "Personal",
];

interface CommunityIntegrationsTabProps {
  onIntegrationPress?: (integration: CommunityIntegration) => void;
}

export function CommunityIntegrationsTab({
  onIntegrationPress,
}: CommunityIntegrationsTabProps) {
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedCategory, setSelectedCategory] = useState("All");

  const categoryParam =
    selectedCategory === "All" ? undefined : selectedCategory.toLowerCase();
  const searchParam = searchQuery.trim() || undefined;

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
      <CommunityIntegrationCard
        integration={item}
        onPress={onIntegrationPress}
      />
    ),
    [onIntegrationPress],
  );

  const keyExtractor = useCallback(
    (item: CommunityIntegration) => item.integrationId,
    [],
  );

  const ListHeader = useCallback(
    () => (
      <View className="flex-row items-center justify-between px-4 py-2">
        <Text className="text-sm font-medium">Community Integrations</Text>
        {total > 0 ? (
          <Text className="text-sm text-muted">{total} total</Text>
        ) : null}
      </View>
    ),
    [total],
  );

  const ListEmpty = useCallback(() => {
    if (isLoading) {
      return (
        <SkeletonGroup>
          <View className="gap-3 px-4 py-4">
            {Array.from({ length: 5 }).map((_, index) => (
              // biome-ignore lint/suspicious/noArrayIndexKey: static skeleton placeholders
              <View key={index} className="flex-row items-center gap-3">
                <Skeleton className="h-12 w-12 rounded-xl" />
                <View className="flex-1 gap-2">
                  <Skeleton className="h-4 w-32 rounded-lg" />
                  <Skeleton className="h-3 w-48 rounded-lg" />
                </View>
              </View>
            ))}
          </View>
        </SkeletonGroup>
      );
    }

    if (error) {
      return (
        <View className="items-center justify-center py-12 px-6">
          <Text className="text-muted text-sm text-center">
            Failed to load community integrations. Please try again.
          </Text>
        </View>
      );
    }

    return (
      <View className="items-center justify-center py-12 px-6">
        <Text className="text-muted text-sm text-center">
          No integrations found
          {searchParam ? ` for "${searchParam}"` : ""}.
        </Text>
      </View>
    );
  }, [isLoading, error, searchParam]);

  const ListFooter = useCallback(() => {
    if (!isFetchingNextPage) return null;
    return (
      <View className="items-center py-4">
        <SkeletonGroup>
          <Skeleton className="h-12 w-full rounded-xl" />
        </SkeletonGroup>
      </View>
    );
  }, [isFetchingNextPage]);

  return (
    <View className="flex-1">
      <View className="px-4 pt-3 pb-2">
        <AppSearchInput
          value={searchQuery}
          onChangeText={setSearchQuery}
          placeholder="Search community integrations..."
          inputClassName="bg-white/5"
        />
      </View>

      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        className="px-4 pb-3"
        contentContainerStyle={{ gap: 8 }}
      >
        {CATEGORY_FILTERS.map((cat) => (
          <Chip
            key={cat}
            size="sm"
            onPress={() => setSelectedCategory(cat)}
            animation="disable-all"
            variant={selectedCategory === cat ? "primary" : "tertiary"}
            color={selectedCategory === cat ? "accent" : "default"}
            className={selectedCategory === cat ? undefined : "bg-white/10"}
          >
            <Chip.Label>{cat}</Chip.Label>
          </Chip>
        ))}
      </ScrollView>

      <FlatList
        data={integrations}
        keyExtractor={keyExtractor}
        renderItem={renderItem}
        ListHeaderComponent={ListHeader}
        ListEmptyComponent={ListEmpty}
        ListFooterComponent={ListFooter}
        onEndReached={handleLoadMore}
        onEndReachedThreshold={0.3}
        contentContainerStyle={{ paddingBottom: 24 }}
        showsVerticalScrollIndicator={false}
      />
    </View>
  );
}
