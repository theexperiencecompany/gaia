import * as Haptics from "expo-haptics";
import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { FlatList, Pressable, RefreshControl, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { Add01Icon, AppIcon, UserGroupIcon } from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import { SidebarMenuButton } from "@/shared/components/sidebar-menu-button";
import { workflowApi } from "../api/workflow-api";
import { WORKFLOW_COLORS } from "../constants/colors";
import { WORKFLOW_COMMUNITY_PAGE_SIZE } from "../constants/timing";
import { useExploreWorkflows } from "../hooks/use-explore-workflows";
import { useWorkflows } from "../hooks/use-workflows";
import type { CommunityWorkflow, Workflow } from "../types/workflow-types";
import { CreateWorkflowModal } from "./create-workflow-modal";
import { CommunityWorkflowsList } from "./list/CommunityWorkflowsList";
import { ExploreWorkflowsList } from "./list/ExploreWorkflowsList";
import { MyWorkflowsList } from "./list/MyWorkflowsList";

interface SectionEntry {
  key: string;
  render: () => React.ReactNode;
}

export function WorkflowListScreen() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { spacing, fontSize } = useResponsive();
  const { workflows, isLoading, isRefreshing, error, refetch } = useWorkflows();
  const { workflows: exploreWorkflows } = useExploreWorkflows();
  const [showCreate, setShowCreate] = useState(false);

  const [communityWorkflows, setCommunityWorkflows] = useState<
    CommunityWorkflow[]
  >([]);
  const [isLoadingCommunity, setIsLoadingCommunity] = useState(false);
  const [isLoadingMoreCommunity, setIsLoadingMoreCommunity] = useState(false);
  const [communityHasMore, setCommunityHasMore] = useState(true);
  const communityOffsetRef = useRef(0);

  const [exploreSearch, setExploreSearch] = useState("");
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null);

  useFocusEffect(
    useCallback(() => {
      void refetch();
    }, [refetch]),
  );

  const loadCommunityWorkflows = useCallback(
    async (reset = false) => {
      if (reset) {
        communityOffsetRef.current = 0;
        setCommunityHasMore(true);
        setIsLoadingCommunity(true);
      } else {
        if (!communityHasMore) return;
        setIsLoadingMoreCommunity(true);
      }
      try {
        const response = await workflowApi.getCommunityWorkflows({
          limit: WORKFLOW_COMMUNITY_PAGE_SIZE,
          offset: communityOffsetRef.current,
        });
        const incoming = response.workflows;
        if (reset) {
          setCommunityWorkflows(incoming);
        } else {
          setCommunityWorkflows((prev) => [...prev, ...incoming]);
        }
        communityOffsetRef.current += incoming.length;
        setCommunityHasMore(incoming.length === WORKFLOW_COMMUNITY_PAGE_SIZE);
      } catch {
        // Silent fail — keep prior community list intact.
      } finally {
        setIsLoadingCommunity(false);
        setIsLoadingMoreCommunity(false);
      }
    },
    [communityHasMore],
  );

  useEffect(() => {
    void loadCommunityWorkflows(true);
    // Intentionally only run once — loadCommunityWorkflows itself depends on
    // `communityHasMore`, but the initial fetch must always proceed.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const allCategories = useMemo(() => {
    const catSet = new Set<string>();
    for (const w of communityWorkflows) {
      for (const c of w.categories ?? []) {
        catSet.add(c);
      }
    }
    for (const w of exploreWorkflows) {
      for (const c of w.categories ?? []) {
        catSet.add(c);
      }
    }
    return Array.from(catSet).sort();
  }, [communityWorkflows, exploreWorkflows]);

  const filteredExploreWorkflows = useMemo(() => {
    let result = exploreWorkflows;
    if (selectedCategory) {
      result = result.filter((w) => w.categories?.includes(selectedCategory));
    }
    if (exploreSearch.trim()) {
      const q = exploreSearch.toLowerCase();
      result = result.filter(
        (w) =>
          w.title.toLowerCase().includes(q) ||
          w.description.toLowerCase().includes(q),
      );
    }
    return result;
  }, [exploreWorkflows, selectedCategory, exploreSearch]);

  const handleCreated = (workflow: Workflow) => {
    setShowCreate(false);
    router.push(`/(app)/workflows/${workflow.id}`);
  };

  const handleLoadMoreCommunity = useCallback(() => {
    if (!isLoadingMoreCommunity && communityHasMore) {
      void loadCommunityWorkflows(false);
    }
  }, [isLoadingMoreCommunity, communityHasMore, loadCommunityWorkflows]);

  const handleRefresh = useCallback(() => {
    void Haptics.selectionAsync();
    void refetch();
    void loadCommunityWorkflows(true);
  }, [refetch, loadCommunityWorkflows]);

  const listRef = useRef<FlatList<SectionEntry>>(null);

  const handleBrowseCommunity = useCallback(() => {
    void Haptics.selectionAsync();
    listRef.current?.scrollToIndex({ index: 2, animated: true });
  }, []);

  const sections: SectionEntry[] = [
    {
      key: "my-workflows",
      render: () => (
        <MyWorkflowsList
          workflows={workflows}
          isLoading={isLoading}
          error={error}
          onRefetch={() => void refetch()}
          onCreate={() => setShowCreate(true)}
          onUpdated={() => void refetch()}
        />
      ),
    },
    {
      key: "explore",
      render: () => (
        <ExploreWorkflowsList
          workflows={exploreWorkflows}
          filtered={filteredExploreWorkflows}
          search={exploreSearch}
          onSearchChange={setExploreSearch}
          categories={allCategories}
          selectedCategory={selectedCategory}
          onCategoryChange={setSelectedCategory}
        />
      ),
    },
    {
      key: "community",
      render: () => (
        <CommunityWorkflowsList
          workflows={communityWorkflows}
          isLoading={isLoadingCommunity}
          isLoadingMore={isLoadingMoreCommunity}
          hasMore={communityHasMore}
          onLoadMore={handleLoadMoreCommunity}
        />
      ),
    },
  ];

  return (
    <View style={{ flex: 1, backgroundColor: WORKFLOW_COLORS.screenBg }}>
      <View
        style={{
          paddingTop: insets.top + spacing.sm,
          paddingHorizontal: spacing.md,
          paddingBottom: spacing.md,
          borderBottomWidth: 1,
          borderBottomColor: WORKFLOW_COLORS.borderSubtle,
          flexDirection: "row",
          alignItems: "center",
          gap: spacing.sm,
        }}
      >
        <SidebarMenuButton />
        <Text
          style={{
            fontSize: fontSize.lg,
            fontWeight: "600",
            color: WORKFLOW_COLORS.textPrimary,
            flex: 1,
          }}
        >
          Workflows
        </Text>

        <Pressable
          onPress={handleBrowseCommunity}
          hitSlop={8}
          accessibilityLabel="Browse community workflows"
          style={({ pressed }) => ({
            width: 36,
            height: 36,
            borderRadius: 999,
            alignItems: "center",
            justifyContent: "center",
            backgroundColor: pressed
              ? "rgba(0,187,255,0.25)"
              : WORKFLOW_COLORS.primarySubtleAlt,
          })}
        >
          <AppIcon
            icon={UserGroupIcon}
            size={18}
            color={WORKFLOW_COLORS.primary}
          />
        </Pressable>

        <Pressable
          onPress={() => {
            void Haptics.selectionAsync();
            setShowCreate(true);
          }}
          hitSlop={8}
          accessibilityLabel="Create new workflow"
          style={({ pressed }) => ({
            width: 36,
            height: 36,
            borderRadius: 999,
            alignItems: "center",
            justifyContent: "center",
            backgroundColor: pressed
              ? "rgba(0,187,255,0.25)"
              : WORKFLOW_COLORS.primarySubtleAlt,
          })}
        >
          <AppIcon icon={Add01Icon} size={18} color={WORKFLOW_COLORS.primary} />
        </Pressable>
      </View>

      <FlatList
        ref={listRef}
        data={sections}
        keyExtractor={(item) => item.key}
        onScrollToIndexFailed={({ index, averageItemLength }) => {
          listRef.current?.scrollToOffset({
            offset: index * averageItemLength,
            animated: true,
          });
        }}
        contentContainerStyle={{
          padding: spacing.md,
          gap: spacing.xl,
          paddingBottom: 40 + insets.bottom,
        }}
        refreshControl={
          <RefreshControl
            refreshing={isRefreshing}
            onRefresh={handleRefresh}
            tintColor={WORKFLOW_COLORS.primary}
          />
        }
        renderItem={({ item }) => <>{item.render()}</>}
        onEndReached={handleLoadMoreCommunity}
        onEndReachedThreshold={0.3}
      />

      <CreateWorkflowModal
        visible={showCreate}
        onClose={() => setShowCreate(false)}
        onCreated={handleCreated}
      />
    </View>
  );
}
