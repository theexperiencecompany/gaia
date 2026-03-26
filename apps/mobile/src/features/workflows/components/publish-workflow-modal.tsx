import { BottomSheetScrollView } from "@gorhom/bottom-sheet";
import * as Clipboard from "expo-clipboard";
import { forwardRef, useImperativeHandle, useMemo, useState } from "react";
import { ActivityIndicator, Alert, Pressable, View } from "react-native";
import {
  AppIcon,
  Cancel01Icon,
  Copy01Icon,
  GlobeIcon,
  Tick02Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import { BottomSheet } from "@/shared/components/ui/bottom-sheet";
import { workflowApi } from "../api/workflow-api";
import type { Workflow } from "../types/workflow-types";

const WEB_APP_URL = process.env.EXPO_PUBLIC_WEB_URL ?? "https://app.gaia.so";

export interface PublishWorkflowModalRef {
  open: (workflow: Workflow) => void;
  close: () => void;
}

interface PublishWorkflowModalProps {
  onPublished: (workflow: Workflow) => void;
  onUnpublished: (workflow: Workflow) => void;
}

export const PublishWorkflowModal = forwardRef<
  PublishWorkflowModalRef,
  PublishWorkflowModalProps
>(({ onPublished, onUnpublished }, ref) => {
  const [isOpen, setIsOpen] = useState(false);
  const [workflow, setWorkflow] = useState<Workflow | null>(null);
  const [isPublishing, setIsPublishing] = useState(false);
  const [isUnpublishing, setIsUnpublishing] = useState(false);
  const [copied, setCopied] = useState(false);
  const { spacing, fontSize } = useResponsive();

  const snapPoints = useMemo(() => ["50%"], []);

  useImperativeHandle(ref, () => ({
    open: (wf: Workflow) => {
      setWorkflow(wf);
      setCopied(false);
      setIsOpen(true);
    },
    close: () => {
      setIsOpen(false);
    },
  }));

  const publicUrl = workflow
    ? `${WEB_APP_URL}/workflows/public/${workflow.id}`
    : "";

  const handleCopyUrl = async () => {
    await Clipboard.setStringAsync(publicUrl);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handlePublish = async () => {
    if (!workflow) return;
    setIsPublishing(true);
    try {
      await workflowApi.publishWorkflow(workflow.id);
      const updated: Workflow = { ...workflow, is_public: true };
      setWorkflow(updated);
      onPublished(updated);
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Failed to publish workflow";
      Alert.alert("Error", message);
    } finally {
      setIsPublishing(false);
    }
  };

  const handleUnpublish = () => {
    if (!workflow) return;
    Alert.alert(
      "Unpublish Workflow",
      "This will remove the workflow from the community. Anyone with the link will no longer be able to access it.",
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Unpublish",
          style: "destructive",
          onPress: async () => {
            setIsUnpublishing(true);
            try {
              await workflowApi.unpublishWorkflow(workflow.id);
              const updated: Workflow = { ...workflow, is_public: false };
              setWorkflow(updated);
              onUnpublished(updated);
              setIsOpen(false);
            } catch (err) {
              const message =
                err instanceof Error
                  ? err.message
                  : "Failed to unpublish workflow";
              Alert.alert("Error", message);
            } finally {
              setIsUnpublishing(false);
            }
          },
        },
      ],
    );
  };

  const isPublished = workflow?.is_public ?? false;

  return (
    <BottomSheet isOpen={isOpen} onOpenChange={setIsOpen}>
      <BottomSheet.Portal>
        <BottomSheet.Overlay />
        <BottomSheet.Content
          snapPoints={snapPoints}
          enableDynamicSizing={false}
          enablePanDownToClose
          backgroundStyle={{ backgroundColor: "#141414" }}
          handleIndicatorStyle={{ backgroundColor: "#3a3a3c", width: 40 }}
        >
          <BottomSheetScrollView
            showsVerticalScrollIndicator={false}
            contentContainerStyle={{
              paddingHorizontal: spacing.md,
              paddingBottom: 40,
              gap: spacing.lg,
            }}
          >
            <View
              style={{
                flexDirection: "row",
                alignItems: "center",
                justifyContent: "space-between",
              }}
            >
              <View
                style={{
                  flexDirection: "row",
                  alignItems: "center",
                  gap: spacing.sm,
                }}
              >
                <AppIcon
                  icon={GlobeIcon}
                  size={18}
                  color={isPublished ? "#22c55e" : "#8e8e93"}
                />
                <Text style={{ fontSize: fontSize.lg, fontWeight: "600" }}>
                  {isPublished ? "Published" : "Publish Workflow"}
                </Text>
              </View>
              <Pressable
                onPress={() => setIsOpen(false)}
                style={{
                  width: 32,
                  height: 32,
                  borderRadius: 999,
                  backgroundColor: "rgba(255,255,255,0.07)",
                  alignItems: "center",
                  justifyContent: "center",
                }}
              >
                <AppIcon icon={Cancel01Icon} size={16} color="#8e8e93" />
              </Pressable>
            </View>

            {isPublished ? (
              <View style={{ gap: spacing.md }}>
                <Text style={{ fontSize: fontSize.sm, color: "#8e8e93" }}>
                  Your workflow is publicly accessible via the link below.
                </Text>

                <View
                  style={{
                    borderRadius: 12,
                    backgroundColor: "#1c1c1e",
                    padding: spacing.md,
                    borderWidth: 1,
                    borderColor: "rgba(34,197,94,0.2)",
                    flexDirection: "row",
                    alignItems: "center",
                    gap: spacing.sm,
                  }}
                >
                  <Text
                    style={{
                      flex: 1,
                      fontSize: fontSize.xs,
                      color: "#22c55e",
                    }}
                    numberOfLines={2}
                  >
                    {publicUrl}
                  </Text>
                  <Pressable
                    onPress={() => {
                      void handleCopyUrl();
                    }}
                    style={{
                      width: 32,
                      height: 32,
                      borderRadius: 8,
                      backgroundColor: copied
                        ? "rgba(34,197,94,0.15)"
                        : "rgba(255,255,255,0.07)",
                      alignItems: "center",
                      justifyContent: "center",
                    }}
                  >
                    <AppIcon
                      icon={copied ? Tick02Icon : Copy01Icon}
                      size={16}
                      color={copied ? "#22c55e" : "#8e8e93"}
                    />
                  </Pressable>
                </View>

                <Pressable
                  onPress={handleUnpublish}
                  disabled={isUnpublishing}
                  style={{
                    borderRadius: 12,
                    paddingVertical: spacing.md,
                    alignItems: "center",
                    justifyContent: "center",
                    flexDirection: "row",
                    gap: spacing.sm,
                    backgroundColor: "rgba(239,68,68,0.1)",
                  }}
                >
                  {isUnpublishing ? (
                    <ActivityIndicator size="small" color="#ef4444" />
                  ) : (
                    <Text
                      style={{
                        fontSize: fontSize.sm,
                        fontWeight: "600",
                        color: "#ef4444",
                      }}
                    >
                      Unpublish
                    </Text>
                  )}
                </Pressable>
              </View>
            ) : (
              <View style={{ gap: spacing.md }}>
                <Text style={{ fontSize: fontSize.sm, color: "#8e8e93" }}>
                  Publishing makes this workflow accessible to anyone with the
                  link and adds it to the community explore section.
                </Text>

                <Pressable
                  onPress={() => {
                    void handlePublish();
                  }}
                  disabled={isPublishing}
                  style={{
                    borderRadius: 12,
                    paddingVertical: spacing.md,
                    alignItems: "center",
                    justifyContent: "center",
                    flexDirection: "row",
                    gap: spacing.sm,
                    backgroundColor: isPublishing
                      ? "rgba(34,197,94,0.08)"
                      : "rgba(34,197,94,0.15)",
                  }}
                >
                  {isPublishing ? (
                    <ActivityIndicator size="small" color="#22c55e" />
                  ) : (
                    <>
                      <AppIcon icon={GlobeIcon} size={16} color="#22c55e" />
                      <Text
                        style={{
                          fontSize: fontSize.sm,
                          fontWeight: "600",
                          color: "#22c55e",
                        }}
                      >
                        Publish to Community
                      </Text>
                    </>
                  )}
                </Pressable>
              </View>
            )}
          </BottomSheetScrollView>
        </BottomSheet.Content>
      </BottomSheet.Portal>
    </BottomSheet>
  );
});

PublishWorkflowModal.displayName = "PublishWorkflowModal";
