import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ActivityIndicator,
  FlatList,
  Pressable,
  RefreshControl,
  ScrollView,
  TextInput,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import {
  Add01Icon,
  AppIcon,
  Cancel01Icon,
  FlowCircleIcon,
  Search01Icon,
  UserGroupIcon,
  ZapIcon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import { workflowApi } from "../api/workflow-api";
import { useExploreWorkflows } from "../hooks/use-explore-workflows";
import { useWorkflows } from "../hooks/use-workflows";
import type { CommunityWorkflow, Workflow } from "../types/workflow-types";
import { CommunityWorkflowCard } from "./community-workflow-card";
import { CreateWorkflowModal } from "./create-workflow-modal";
import { WorkflowCard } from "./workflow-card";
import { WorkflowListSkeleton } from "./workflow-skeletons";

const COMMUNITY_PAGE_SIZE = 12;

export function WorkflowListScreen() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { spacing, fontSize, moderateScale } = useResponsive();
  const { workflows, isLoading, isRefreshing, error, refetch } = useWorkflows();
  const { workflows: exploreWorkflows } = useExploreWorkflows();
  const [showCreate, setShowCreate] = useState(false);

  // Community workflows with pagination
  const [communityWorkflows, setCommunityWorkflows] = useState<
    CommunityWorkflow[]
  >([]);
  const [isLoadingCommunity, setIsLoadingCommunity] = useState(false);
  const [isLoadingMoreCommunity, setIsLoadingMoreCommunity] = useState(false);
  const [communityHasMore, setCommunityHasMore] = useState(true);
  const communityOffsetRef = useRef(0);

  // Explore section: search + category filter
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
          limit: COMMUNITY_PAGE_SIZE,
          offset: communityOffsetRef.current,
        });
        const incoming = response.workflows;
        if (reset) {
          setCommunityWorkflows(incoming);
        } else {
          setCommunityWorkflows((prev) => [...prev, ...incoming]);
        }
        communityOffsetRef.current += incoming.length;
        setCommunityHasMore(incoming.length === COMMUNITY_PAGE_SIZE);
      } catch {
        // Silent fail
      } finally {
        setIsLoadingCommunity(false);
        setIsLoadingMoreCommunity(false);
      }
    },
    [communityHasMore],
  );

  useEffect(() => {
    void loadCommunityWorkflows(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Derive all unique categories from community + explore workflows
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

  // Filtered explore workflows
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

  const renderCommunityBanner = () => (
    <View
      style={{
        borderRadius: moderateScale(20, 0.5),
        backgroundColor: "rgba(0,187,255,0.06)",
        borderWidth: 1,
        borderColor: "rgba(0,187,255,0.15)",
        padding: spacing.lg,
        gap: spacing.md,
      }}
    >
      <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
        <AppIcon icon={UserGroupIcon} size={22} color="#00bbff" />
        <Text
          style={{
            fontSize: fontSize.base,
            fontWeight: "600",
            color: "#fff",
          }}
        >
          Explore the Community
        </Text>
      </View>
      <Text style={{ fontSize: fontSize.xs, color: "#8e8e93", lineHeight: 18 }}>
        Discover community workflows or publish your own for others to use.
      </Text>
      <Pressable
        onPress={() => setShowCreate(true)}
        style={({ pressed }) => ({
          borderRadius: moderateScale(12, 0.5),
          paddingHorizontal: spacing.lg,
          paddingVertical: spacing.sm + 2,
          backgroundColor: pressed ? "#009ed9" : "#00bbff",
          alignSelf: "flex-start",
          flexDirection: "row",
          alignItems: "center",
          gap: 6,
        })}
      >
        <AppIcon icon={ZapIcon} size={14} color="#000" />
        <Text
          style={{
            fontSize: fontSize.sm,
            fontWeight: "600",
            color: "#000",
          }}
        >
          Create New Workflow
        </Text>
      </Pressable>
    </View>
  );

  const renderMyWorkflows = () => {
    const content = (() => {
      if (isLoading) {
        return <WorkflowListSkeleton />;
      }

      if (error) {
        return (
          <View
            style={{
              paddingVertical: spacing.xl,
              alignItems: "center",
              gap: spacing.md,
            }}
          >
            <Text
              style={{
                fontSize: fontSize.sm,
                color: "#ef4444",
                textAlign: "center",
              }}
            >
              {error}
            </Text>
            <Pressable onPress={() => void refetch()}>
              <Text style={{ fontSize: fontSize.sm, color: "#00bbff" }}>
                Try again
              </Text>
            </Pressable>
          </View>
        );
      }

      if (workflows.length === 0) {
        return (
          <View
            style={{
              paddingVertical: spacing.xl * 2,
              alignItems: "center",
              gap: spacing.md,
              borderRadius: moderateScale(24, 0.5),
              borderWidth: 2,
              borderStyle: "dashed",
              borderColor: "rgba(39,39,42,1)",
              backgroundColor: "rgba(39,39,42,0.3)",
            }}
          >
            <AppIcon icon={FlowCircleIcon} size={48} color="#333" />
            <View style={{ alignItems: "center", gap: 4 }}>
              <Text
                style={{
                  fontSize: fontSize.base,
                  fontWeight: "500",
                  color: "#d4d4d8",
                  textAlign: "center",
                }}
              >
                No workflows yet
              </Text>
              <Text
                style={{
                  fontSize: fontSize.sm,
                  color: "#71717a",
                  textAlign: "center",
                  maxWidth: 260,
                }}
              >
                Create your first workflow to get started
              </Text>
            </View>
            <Pressable
              onPress={() => setShowCreate(true)}
              style={({ pressed }) => ({
                borderRadius: moderateScale(12, 0.5),
                paddingHorizontal: spacing.lg,
                paddingVertical: spacing.md,
                backgroundColor: pressed ? "#009ed9" : "#00bbff",
                marginTop: spacing.sm,
              })}
            >
              <Text
                style={{
                  fontSize: fontSize.sm,
                  fontWeight: "600",
                  color: "#000",
                }}
              >
                Create your first workflow
              </Text>
            </Pressable>
          </View>
        );
      }

      return (
        <View style={{ gap: spacing.sm }}>
          {workflows.map((workflow) => (
            <WorkflowCard
              key={workflow.id}
              workflow={workflow}
              onUpdated={() => void refetch()}
            />
          ))}
        </View>
      );
    })();

    return (
      <View style={{ gap: spacing.md }}>
        <SectionHeader
          title="My Workflows"
          description="Automate tasks and run workflows on demand or on a schedule."
          count={
            !isLoading && workflows.length > 0 ? workflows.length : undefined
          }
        />
        {content}
      </View>
    );
  };

  const renderExploreSection = () => {
    if (exploreWorkflows.length === 0 && !exploreSearch && !selectedCategory) {
      return null;
    }

    return (
      <View style={{ gap: spacing.md }}>
        <SectionHeader
          title="Explore & Discover"
          description="See what's possible with real examples that actually work!"
          count={
            filteredExploreWorkflows.length > 0
              ? filteredExploreWorkflows.length
              : undefined
          }
        />

        {/* Search bar */}
        <View
          style={{
            flexDirection: "row",
            alignItems: "center",
            gap: spacing.xs,
            backgroundColor: "rgba(255,255,255,0.06)",
            borderRadius: moderateScale(10, 0.5),
            paddingHorizontal: spacing.sm,
            borderWidth: 1,
            borderColor: "rgba(255,255,255,0.08)",
          }}
        >
          <AppIcon icon={Search01Icon} size={14} color="#52525b" />
          <TextInput
            placeholder="Search workflows..."
            placeholderTextColor="#52525b"
            value={exploreSearch}
            onChangeText={setExploreSearch}
            style={{
              flex: 1,
              paddingVertical: moderateScale(9, 0.5),
              fontSize: fontSize.sm,
              color: "#e4e4e7",
            }}
            autoCapitalize="none"
            autoCorrect={false}
            returnKeyType="search"
          />
          {exploreSearch.length > 0 && (
            <Pressable onPress={() => setExploreSearch("")}>
              <AppIcon icon={Cancel01Icon} size={14} color="#52525b" />
            </Pressable>
          )}
        </View>

        {/* Category filter chips */}
        {allCategories.length > 0 && (
          <ScrollView
            horizontal
            showsHorizontalScrollIndicator={false}
            contentContainerStyle={{ gap: 8, paddingVertical: 2 }}
          >
            <Pressable
              onPress={() => setSelectedCategory(null)}
              style={{
                paddingHorizontal: 12,
                paddingVertical: 5,
                borderRadius: 999,
                backgroundColor:
                  selectedCategory === null
                    ? "#00bbff"
                    : "rgba(255,255,255,0.07)",
                borderWidth: 1,
                borderColor:
                  selectedCategory === null
                    ? "#00bbff"
                    : "rgba(255,255,255,0.1)",
              }}
            >
              <Text
                style={{
                  fontSize: fontSize.xs,
                  color: selectedCategory === null ? "#000" : "#a1a1aa",
                  fontWeight: selectedCategory === null ? "600" : "400",
                }}
              >
                All
              </Text>
            </Pressable>
            {allCategories.map((cat) => (
              <Pressable
                key={cat}
                onPress={() =>
                  setSelectedCategory(selectedCategory === cat ? null : cat)
                }
                style={{
                  paddingHorizontal: 12,
                  paddingVertical: 5,
                  borderRadius: 999,
                  backgroundColor:
                    selectedCategory === cat
                      ? "#00bbff"
                      : "rgba(255,255,255,0.07)",
                  borderWidth: 1,
                  borderColor:
                    selectedCategory === cat
                      ? "#00bbff"
                      : "rgba(255,255,255,0.1)",
                }}
              >
                <Text
                  style={{
                    fontSize: fontSize.xs,
                    color: selectedCategory === cat ? "#000" : "#a1a1aa",
                    fontWeight: selectedCategory === cat ? "600" : "400",
                  }}
                >
                  {cat}
                </Text>
              </Pressable>
            ))}
          </ScrollView>
        )}

        {/* Workflow cards */}
        {filteredExploreWorkflows.length === 0 ? (
          <View
            style={{
              paddingVertical: spacing.xl,
              alignItems: "center",
            }}
          >
            <Text style={{ fontSize: fontSize.sm, color: "#52525b" }}>
              No workflows match your search
            </Text>
          </View>
        ) : (
          <View style={{ gap: spacing.sm }}>
            {filteredExploreWorkflows.map((w) => (
              <CommunityWorkflowCard key={w.id} workflow={w} />
            ))}
          </View>
        )}
      </View>
    );
  };

  const renderCommunitySection = () => {
    if (isLoadingCommunity) {
      return (
        <View style={{ gap: spacing.md }}>
          <SectionHeader
            title="Community Workflows"
            description="Check out what others have built and grab anything that looks useful!"
          />
          <WorkflowListSkeleton />
        </View>
      );
    }

    if (communityWorkflows.length === 0) return null;

    return (
      <View style={{ gap: spacing.md }}>
        <SectionHeader
          title="Community Workflows"
          description="Check out what others have built and grab anything that looks useful!"
          count={communityWorkflows.length}
        />
        <View style={{ gap: spacing.sm }}>
          {communityWorkflows.map((w) => (
            <CommunityWorkflowCard key={w.id} workflow={w} />
          ))}
        </View>

        {/* Load more */}
        {communityHasMore && (
          <Pressable
            onPress={handleLoadMoreCommunity}
            disabled={isLoadingMoreCommunity}
            style={{
              alignItems: "center",
              paddingVertical: spacing.sm,
              gap: 6,
            }}
          >
            {isLoadingMoreCommunity ? (
              <ActivityIndicator size="small" color="#00bbff" />
            ) : (
              <Text style={{ fontSize: fontSize.sm, color: "#00bbff" }}>
                Load more
              </Text>
            )}
          </Pressable>
        )}
      </View>
    );
  };

  const sections = [
    { key: "banner", render: renderCommunityBanner },
    { key: "my-workflows", render: renderMyWorkflows },
    { key: "explore", render: renderExploreSection },
    { key: "community", render: renderCommunitySection },
  ];

  return (
    <View style={{ flex: 1, backgroundColor: "#131416" }}>
      {/* Header bar */}
      <View
        style={{
          paddingTop: insets.top + spacing.sm,
          paddingHorizontal: spacing.md,
          paddingBottom: spacing.md,
          borderBottomWidth: 1,
          borderBottomColor: "rgba(255,255,255,0.08)",
          flexDirection: "row",
          alignItems: "center",
        }}
      >
        <Text
          style={{
            fontSize: fontSize.lg,
            fontWeight: "600",
            color: "#fff",
            flex: 1,
          }}
        >
          Workflows
        </Text>

        <Pressable
          onPress={() => setShowCreate(true)}
          style={({ pressed }) => ({
            width: 36,
            height: 36,
            borderRadius: 999,
            alignItems: "center",
            justifyContent: "center",
            backgroundColor: pressed
              ? "rgba(0,187,255,0.25)"
              : "rgba(0,187,255,0.15)",
          })}
        >
          <AppIcon icon={Add01Icon} size={18} color="#00bbff" />
        </Pressable>
      </View>

      <FlatList
        data={sections}
        keyExtractor={(item) => item.key}
        contentContainerStyle={{
          padding: spacing.md,
          gap: spacing.xl,
          paddingBottom: 40 + insets.bottom,
        }}
        refreshControl={
          <RefreshControl
            refreshing={isRefreshing}
            onRefresh={() => {
              void refetch();
              void loadCommunityWorkflows(true);
            }}
            tintColor="#00bbff"
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

function SectionHeader({
  title,
  description,
  count,
}: {
  title: string;
  description: string;
  count?: number;
}) {
  const { fontSize } = useResponsive();

  return (
    <View style={{ gap: 4 }}>
      <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
        <Text
          style={{
            fontSize: fontSize.lg,
            fontWeight: "500",
            color: "#f4f4f5",
          }}
        >
          {title}
        </Text>
        {count !== undefined && count > 0 && (
          <View
            style={{
              borderRadius: 999,
              backgroundColor: "rgba(39,39,42,1)",
              paddingHorizontal: 10,
              paddingVertical: 2,
            }}
          >
            <Text
              style={{
                fontSize: fontSize.sm,
                fontWeight: "500",
                color: "#a1a1aa",
              }}
            >
              {count}
            </Text>
          </View>
        )}
      </View>
      <Text
        style={{
          fontSize: fontSize.sm,
          fontWeight: "300",
          color: "#71717a",
        }}
      >
        {description}
      </Text>
    </View>
  );
}
