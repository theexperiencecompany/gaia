import { BottomSheetScrollView } from "@gorhom/bottom-sheet";
import * as Haptics from "expo-haptics";
import {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
} from "react";
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
import {
  AppFilterChipGroup,
  type AppFilterChipOption,
} from "@/shared/components/ui/app-filter-chip-group";
import { BottomSheet } from "@/shared/components/ui/bottom-sheet";
import { workflowApi } from "../api/workflow-api";
import { WORKFLOW_REGENERATE_AUTO_CLOSE_MS } from "../constants/timing";
import type { Workflow } from "../types/workflow-types";

type RegenerateReasonKey =
  | "too_complex"
  | "missing_functionality"
  | "wrong_tools"
  | "alternative_approach";

interface RegenerateReason {
  key: RegenerateReasonKey;
  label: string;
  prompt: string;
}

const REGENERATE_REASONS: readonly RegenerateReason[] = [
  {
    key: "too_complex",
    label: "Too Complex",
    prompt: "The current steps are too complex. Simplify them.",
  },
  {
    key: "missing_functionality",
    label: "Missing Functionality",
    prompt: "The current steps are missing key functionality.",
  },
  {
    key: "wrong_tools",
    label: "Wrong Tools",
    prompt: "The current steps use the wrong tools. Use different tools.",
  },
  {
    key: "alternative_approach",
    label: "Alternative Approach",
    prompt: "Take a fundamentally different approach to solve this.",
  },
] as const;

const REGENERATE_REASON_OPTIONS: readonly AppFilterChipOption[] =
  REGENERATE_REASONS.map((r) => ({ key: r.key, label: r.label }));

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
  const [reasonKey, setReasonKey] = useState<RegenerateReasonKey | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const { spacing, fontSize } = useResponsive();
  const closeTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const snapPoints = useMemo(() => ["55%"], []);

  const clearCloseTimeout = () => {
    if (closeTimeoutRef.current) {
      clearTimeout(closeTimeoutRef.current);
      closeTimeoutRef.current = null;
    }
  };

  useEffect(() => clearCloseTimeout, []);

  useImperativeHandle(ref, () => ({
    open: (wf: Workflow) => {
      clearCloseTimeout();
      setWorkflow(wf);
      setInstruction("");
      setReasonKey(null);
      setSuccessMessage(null);
      setIsOpen(true);
    },
    close: () => {
      clearCloseTimeout();
      setIsOpen(false);
    },
  }));

  const handleSheetChange = (open: boolean) => {
    if (!open) clearCloseTimeout();
    setIsOpen(open);
  };

  const handleRegenerate = async () => {
    if (!workflow) return;
    setIsLoading(true);
    setSuccessMessage(null);
    try {
      const reason = REGENERATE_REASONS.find((r) => r.key === reasonKey);
      const customText = instruction.trim();
      const composed = [reason?.prompt, customText]
        .filter((part): part is string => Boolean(part))
        .join(" ");
      const response = await workflowApi.regenerateWorkflowSteps(workflow.id, {
        instruction: composed.length > 0 ? composed : undefined,
        force_different_tools: true,
      });
      setSuccessMessage("Steps regenerated successfully");
      void Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
      onRegenerated(response.workflow);
      clearCloseTimeout();
      closeTimeoutRef.current = setTimeout(() => {
        closeTimeoutRef.current = null;
        setIsOpen(false);
      }, WORKFLOW_REGENERATE_AUTO_CLOSE_MS);
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Failed to regenerate steps";
      Alert.alert("Error", message);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <BottomSheet isOpen={isOpen} onOpenChange={handleSheetChange}>
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
                onPress={() => handleSheetChange(false)}
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
                Reason (optional)
              </Text>
              <AppFilterChipGroup
                options={REGENERATE_REASON_OPTIONS}
                selectedKey={reasonKey}
                onSelect={(key) =>
                  setReasonKey((key as RegenerateReasonKey | undefined) ?? null)
                }
                allowsEmptySelection
              />
            </View>

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
