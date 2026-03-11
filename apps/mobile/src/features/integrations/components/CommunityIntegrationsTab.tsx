import { useCallback, useState } from "react";
import {
  ActivityIndicator,
  FlatList,
  Pressable,
  ScrollView,
  TextInput,
  View,
} from "react-native";
import { HugeiconsIcon, Search01Icon } from "@/components/icons";
import { Text } from "@/components/ui/text";
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
        <View className="items-center justify-center py-12">
          <ActivityIndicator size="large" color="#8e8e93" />
          <Text className="text-muted text-sm mt-3">
            Loading integrations...
          </Text>
        </View>
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
        <ActivityIndicator size="small" color="#8e8e93" />
      </View>
    );
  }, [isFetchingNextPage]);

  return (
    <View className="flex-1">
      <View className="px-4 pt-3 pb-2">
        <View className="flex-row items-center rounded-xl px-3 py-2 bg-muted/10">
          <HugeiconsIcon icon={Search01Icon} size={18} color="#8e8e93" />
          <TextInput
            className="flex-1 ml-2 text-foreground text-sm"
            placeholder="Search community integrations..."
            placeholderTextColor="#6b6b6b"
            value={searchQuery}
            onChangeText={setSearchQuery}
            returnKeyType="search"
          />
        </View>
      </View>

      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        className="px-4 pb-3"
        contentContainerStyle={{ gap: 8 }}
      >
        {CATEGORY_FILTERS.map((cat) => (
          <Pressable
            key={cat}
            onPress={() => setSelectedCategory(cat)}
            className={`px-3 py-1.5 rounded-full ${
              selectedCategory === cat
                ? "bg-accent"
                : "bg-muted/10"
            }`}
          >
            <Text
              className={`text-xs font-medium ${
                selectedCategory === cat ? "text-accent-foreground" : "text-muted"
              }`}
            >
              {cat}
            </Text>
          </Pressable>
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
