import { BottomSheetScrollView } from "@gorhom/bottom-sheet";
import { forwardRef, useImperativeHandle, useMemo, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  Pressable,
  TextInput,
  View,
} from "react-native";
import {
  AppIcon,
  Cancel01Icon,
  MagicWand01Icon,
  RepeatIcon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import { BottomSheet } from "@/shared/components/ui/bottom-sheet";
import { workflowApi } from "../api/workflow-api";
import type { Workflow } from "../types/workflow-types";

export interface RegenerateStepsSheetRef {
  open: (workflow: Workflow) => void;
  close: () => void;
}

interface RegenerateStepsSheetProps {
  onRegenerated: (workflow: Workflow) => void;
}

export const RegenerateStepsSheet = forwardRef<
  RegenerateStepsSheetRef,
  RegenerateStepsSheetProps
>(({ onRegenerated }, ref) => {
  const [isOpen, setIsOpen] = useState(false);
  const [workflow, setWorkflow] = useState<Workflow | null>(null);
  const [instruction, setInstruction] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const { spacing, fontSize } = useResponsive();

  const snapPoints = useMemo(() => ["55%"], []);

  useImperativeHandle(ref, () => ({
    open: (wf: Workflow) => {
      setWorkflow(wf);
      setInstruction("");
      setSuccessMessage(null);
      setIsOpen(true);
    },
    close: () => {
      setIsOpen(false);
    },
  }));

  const handleRegenerate = async () => {
    if (!workflow) return;
    setIsLoading(true);
    setSuccessMessage(null);
    try {
      const response = await workflowApi.regenerateWorkflowSteps(workflow.id, {
        instruction: instruction.trim() || undefined,
        force_different_tools: true,
      });
      setSuccessMessage("Steps regenerated successfully");
      onRegenerated(response.workflow);
      setTimeout(() => {
        setIsOpen(false);
      }, 1500);
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Failed to regenerate steps";
      Alert.alert("Error", message);
    } finally {
      setIsLoading(false);
    }
  };

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
                <AppIcon icon={RepeatIcon} size={18} color="#00bbff" />
                <Text style={{ fontSize: fontSize.lg, fontWeight: "600" }}>
                  Regenerate Steps
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

            {workflow && (
              <Text style={{ fontSize: fontSize.sm, color: "#8e8e93" }}>
                Regenerating steps for{" "}
                <Text style={{ color: "#e4e4e7", fontWeight: "500" }}>
                  {workflow.title}
                </Text>
              </Text>
            )}

            <View style={{ gap: spacing.sm }}>
              <Text
                style={{
                  fontSize: fontSize.xs,
                  color: "#8e8e93",
                  textTransform: "uppercase",
                  letterSpacing: 1,
                }}
              >
                Custom Instructions (optional)
              </Text>
              <TextInput
                value={instruction}
                onChangeText={setInstruction}
                placeholder="e.g. Focus on email automation, use fewer steps..."
                placeholderTextColor="#4a4a4e"
                multiline
                numberOfLines={3}
                style={{
                  backgroundColor: "#1c1c1e",
                  borderRadius: 12,
                  padding: spacing.md,
                  color: "#e4e4e7",
                  fontSize: fontSize.sm,
                  lineHeight: 20,
                  minHeight: 80,
                  textAlignVertical: "top",
                  borderWidth: 1,
                  borderColor: "rgba(255,255,255,0.08)",
                }}
              />
            </View>

            {successMessage && (
              <Text
                style={{
                  fontSize: fontSize.sm,
                  color: "#22c55e",
                  textAlign: "center",
                }}
              >
                {successMessage}
              </Text>
            )}

            <Pressable
              onPress={() => {
                void handleRegenerate();
              }}
              disabled={isLoading}
              style={{
                borderRadius: 12,
                paddingVertical: spacing.md,
                alignItems: "center",
                justifyContent: "center",
                flexDirection: "row",
                gap: spacing.sm,
                backgroundColor: isLoading
                  ? "rgba(0,187,255,0.08)"
                  : "rgba(0,187,255,0.15)",
              }}
            >
              {isLoading ? (
                <ActivityIndicator size="small" color="#00bbff" />
              ) : (
                <>
                  <AppIcon icon={MagicWand01Icon} size={16} color="#00bbff" />
                  <Text
                    style={{
                      fontSize: fontSize.sm,
                      fontWeight: "600",
                      color: "#00bbff",
                    }}
                  >
                    Regenerate Steps
                  </Text>
                </>
              )}
            </Pressable>
          </BottomSheetScrollView>
        </BottomSheet.Content>
      </BottomSheet.Portal>
    </BottomSheet>
  );
});

RegenerateStepsSheet.displayName = "RegenerateStepsSheet";
