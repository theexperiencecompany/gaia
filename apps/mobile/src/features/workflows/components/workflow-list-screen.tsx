import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useState } from "react";
import {
  ActivityIndicator,
  FlatList,
  Pressable,
  RefreshControl,
  View,
} from "react-native";
import {
  Add01Icon,
  ArrowLeft01Icon,
  FlowCircleIcon,
  HugeiconsIcon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import { useExploreWorkflows } from "../hooks/use-explore-workflows";
import { useWorkflows } from "../hooks/use-workflows";
import type { Workflow } from "../types/workflow-types";
import { CommunityWorkflowCard } from "./community-workflow-card";
import { CreateWorkflowModal } from "./create-workflow-modal";
import { WorkflowCard } from "./workflow-card";

export function WorkflowListScreen() {
  const router = useRouter();
  const { spacing, fontSize, moderateScale } = useResponsive();
  const { workflows, isLoading, isRefreshing, error, refetch } = useWorkflows();
  const { workflows: exploreWorkflows } = useExploreWorkflows();
  const [showCreate, setShowCreate] = useState(false);

  // Refetch whenever we return to this screen (e.g. after a delete in detail)
  useFocusEffect(
    useCallback(() => {
      void refetch();
    }, [refetch]),
  );

  const handleCreated = (workflow: Workflow) => {
    setShowCreate(false);
    router.push(`/(app)/workflows/${workflow.id}`);
  };

  return (
    <View style={{ flex: 1, backgroundColor: "#0b0c0f" }}>
      <View
        style={{
          paddingTop: spacing.xl * 2,
          paddingHorizontal: spacing.md,
          paddingBottom: spacing.md,
          borderBottomWidth: 1,
          borderBottomColor: "rgba(255,255,255,0.08)",
          flexDirection: "row",
          alignItems: "center",
        }}
      >
        <Pressable
          onPress={() => router.back()}
          style={{
            width: 36,
            height: 36,
            borderRadius: 999,
            alignItems: "center",
            justifyContent: "center",
            backgroundColor: "rgba(255,255,255,0.05)",
          }}
        >
          <HugeiconsIcon icon={ArrowLeft01Icon} size={18} color="#fff" />
        </Pressable>

        <Text
          style={{
            marginLeft: spacing.md,
            fontSize: fontSize.base,
            fontWeight: "600",
            color: "#fff",
            flex: 1,
          }}
        >
          Workflows
        </Text>

        <Pressable
          onPress={() => setShowCreate(true)}
          style={{
            width: 36,
            height: 36,
            borderRadius: 999,
            alignItems: "center",
            justifyContent: "center",
            backgroundColor: "rgba(22,193,255,0.15)",
          }}
        >
          <HugeiconsIcon icon={Add01Icon} size={18} color="#16c1ff" />
        </Pressable>
      </View>

      {isLoading ? (
        <View
          style={{ flex: 1, alignItems: "center", justifyContent: "center" }}
        >
          <ActivityIndicator size="large" color="#16c1ff" />
        </View>
      ) : error ? (
        <View
          style={{
            flex: 1,
            alignItems: "center",
            justifyContent: "center",
            paddingHorizontal: spacing.xl,
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
          <Pressable
            onPress={() => {
              void refetch();
            }}
            style={{ marginTop: spacing.md }}
          >
            <Text style={{ fontSize: fontSize.sm, color: "#16c1ff" }}>
              Try again
            </Text>
          </Pressable>
        </View>
      ) : (
        <FlatList
          data={workflows}
          keyExtractor={(item) => item.id}
          contentContainerStyle={{
            padding: spacing.md,
            gap: spacing.sm,
            paddingBottom: 40,
          }}
          refreshControl={
            <RefreshControl
              refreshing={isRefreshing}
              onRefresh={() => {
                void refetch();
              }}
              tintColor="#16c1ff"
            />
          }
          ListEmptyComponent={
            <View
              style={{
                paddingVertical: spacing.xl * 2,
                alignItems: "center",
                gap: spacing.md,
              }}
            >
              <HugeiconsIcon icon={FlowCircleIcon} size={48} color="#333" />
              <Text
                style={{
                  fontSize: fontSize.base,
                  color: "#555",
                  textAlign: "center",
                }}
              >
                No workflows yet
              </Text>
              <Text
                style={{
                  fontSize: fontSize.sm,
                  color: "#444",
                  textAlign: "center",
                  maxWidth: 260,
                }}
              >
                Automate your tasks with AI-powered workflows
              </Text>
              <Pressable
                onPress={() => setShowCreate(true)}
                style={{
                  borderRadius: moderateScale(12, 0.5),
                  paddingHorizontal: spacing.lg,
                  paddingVertical: spacing.md,
                  backgroundColor: "#16c1ff",
                  marginTop: spacing.sm,
                }}
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
          }
          renderItem={({ item }) => <WorkflowCard workflow={item} />}
          ListFooterComponent={
            exploreWorkflows.length > 0 ? (
              <View style={{ marginTop: spacing.xl, gap: spacing.sm }}>
                <Text
                  style={{
                    fontSize: fontSize.xs,
                    color: "#8a9099",
                    textTransform: "uppercase",
                    letterSpacing: 1.2,
                  }}
                >
                  Explore
                </Text>
                {exploreWorkflows.slice(0, 6).map((w) => (
                  <CommunityWorkflowCard key={w.id} workflow={w} />
                ))}
              </View>
            ) : null
          }
        />
      )}

      <CreateWorkflowModal
        visible={showCreate}
        onClose={() => setShowCreate(false)}
        onCreated={handleCreated}
      />
    </View>
  );
}
