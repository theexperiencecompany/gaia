import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useEffect, useState } from "react";
import {
  FlatList,
  Pressable,
  RefreshControl,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import {
  Add01Icon,
  AppIcon,
  FlowCircleIcon,
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

export function WorkflowListScreen() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { spacing, fontSize, moderateScale } = useResponsive();
  const { workflows, isLoading, isRefreshing, error, refetch } = useWorkflows();
  const { workflows: exploreWorkflows } = useExploreWorkflows();
  const [showCreate, setShowCreate] = useState(false);
  const [communityWorkflows, setCommunityWorkflows] = useState<
    CommunityWorkflow[]
  >([]);
  const [isLoadingCommunity, setIsLoadingCommunity] = useState(false);

  useFocusEffect(
    useCallback(() => {
      void refetch();
    }, [refetch]),
  );

  useEffect(() => {
    const loadCommunity = async () => {
      setIsLoadingCommunity(true);
      try {
        const response = await workflowApi.getCommunityWorkflows({
          limit: 12,
        });
        setCommunityWorkflows(response.workflows);
      } catch {
        // Silent fail for community section
      } finally {
        setIsLoadingCommunity(false);
      }
    };
    void loadCommunity();
  }, []);

  const handleCreated = (workflow: Workflow) => {
    setShowCreate(false);
    router.push(`/(app)/workflows/${workflow.id}`);
  };

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
            <WorkflowCard key={workflow.id} workflow={workflow} />
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
    if (exploreWorkflows.length === 0) return null;

    return (
      <View style={{ gap: spacing.md }}>
        <SectionHeader
          title="Explore & Discover"
          description="See what's possible with real examples that actually work!"
          count={exploreWorkflows.length}
        />
        <View style={{ gap: spacing.sm }}>
          {exploreWorkflows.slice(0, 8).map((w) => (
            <CommunityWorkflowCard key={w.id} workflow={w} />
          ))}
        </View>
      </View>
    );
  };

  const renderCommunitySection = () => {
    if (isLoadingCommunity) {
      return <WorkflowListSkeleton />;
    }

    if (communityWorkflows.length === 0) return null;

    return (
      <View style={{ gap: spacing.md }}>
        <SectionHeader
          title="Community Workflows"
          description="Check out what others have built and grab anything that looks useful!"
        />
        <View style={{ gap: spacing.sm }}>
          {communityWorkflows.map((w) => (
            <CommunityWorkflowCard key={w.id} workflow={w} />
          ))}
        </View>
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
            onRefresh={() => void refetch()}
            tintColor="#00bbff"
          />
        }
        renderItem={({ item }) => <>{item.render()}</>}
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
