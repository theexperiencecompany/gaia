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
  Tick02Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import { BottomSheet } from "@/shared/components/ui/bottom-sheet";
import { workflowApi } from "../api/workflow-api";
import type { Workflow } from "../types/workflow-types";

export interface GeneratePromptSheetRef {
  open: (workflow: Workflow) => void;
  close: () => void;
}

interface GeneratePromptSheetProps {
  onPromptSelected: (prompt: string) => void;
}

export const GeneratePromptSheet = forwardRef<
  GeneratePromptSheetRef,
  GeneratePromptSheetProps
>(({ onPromptSelected }, ref) => {
  const [isOpen, setIsOpen] = useState(false);
  const [workflow, setWorkflow] = useState<Workflow | null>(null);
  const [description, setDescription] = useState("");
  const [generatedPrompt, setGeneratedPrompt] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const { spacing, fontSize } = useResponsive();

  const snapPoints = useMemo(() => ["75%"], []);

  useImperativeHandle(ref, () => ({
    open: (wf: Workflow) => {
      setWorkflow(wf);
      setDescription("");
      setGeneratedPrompt(null);
      setIsOpen(true);
    },
    close: () => {
      setIsOpen(false);
    },
  }));

  const handleGenerate = async () => {
    if (!workflow) return;
    setIsLoading(true);
    try {
      const response = await workflowApi.generatePrompt({
        title: workflow.title,
        description: description.trim() || workflow.description,
        existing_prompt: workflow.prompt || undefined,
      });
      setGeneratedPrompt(response.prompt);
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Failed to generate prompt";
      Alert.alert("Error", message);
    } finally {
      setIsLoading(false);
    }
  };

  const handleUsePrompt = () => {
    if (!generatedPrompt) return;
    onPromptSelected(generatedPrompt);
    setIsOpen(false);
  };

  const handleRegenerate = () => {
    setGeneratedPrompt(null);
    void handleGenerate();
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
                <AppIcon icon={MagicWand01Icon} size={18} color="#a78bfa" />
                <Text style={{ fontSize: fontSize.lg, fontWeight: "600" }}>
                  Generate Prompt
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

            <View style={{ gap: spacing.sm }}>
              <Text
                style={{
                  fontSize: fontSize.xs,
                  color: "#8e8e93",
                  textTransform: "uppercase",
                  letterSpacing: 1,
                }}
              >
                Describe what this workflow should do
              </Text>
              <TextInput
                value={description}
                onChangeText={setDescription}
                placeholder="e.g. Send a daily email summary of my tasks and calendar events..."
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

            {!generatedPrompt && (
              <Pressable
                onPress={() => {
                  void handleGenerate();
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
                    ? "rgba(167,139,250,0.08)"
                    : "rgba(167,139,250,0.15)",
                }}
              >
                {isLoading ? (
                  <ActivityIndicator size="small" color="#a78bfa" />
                ) : (
                  <>
                    <AppIcon icon={MagicWand01Icon} size={16} color="#a78bfa" />
                    <Text
                      style={{
                        fontSize: fontSize.sm,
                        fontWeight: "600",
                        color: "#a78bfa",
                      }}
                    >
                      Generate Prompt
                    </Text>
                  </>
                )}
              </Pressable>
            )}

            {generatedPrompt && (
              <View style={{ gap: spacing.md }}>
                <Text
                  style={{
                    fontSize: fontSize.xs,
                    color: "#8e8e93",
                    textTransform: "uppercase",
                    letterSpacing: 1,
                  }}
                >
                  Generated Prompt
                </Text>

                <View
                  style={{
                    borderRadius: 12,
                    backgroundColor: "#1c1c1e",
                    padding: spacing.md,
                    borderWidth: 1,
                    borderColor: "rgba(167,139,250,0.2)",
                  }}
                >
                  <Text
                    style={{
                      fontSize: fontSize.sm,
                      color: "#c0c6cf",
                      lineHeight: 20,
                    }}
                  >
                    {generatedPrompt}
                  </Text>
                </View>

                <View style={{ flexDirection: "row", gap: spacing.sm }}>
                  <Pressable
                    onPress={handleRegenerate}
                    disabled={isLoading}
                    style={{
                      flex: 1,
                      borderRadius: 12,
                      paddingVertical: spacing.md,
                      alignItems: "center",
                      justifyContent: "center",
                      flexDirection: "row",
                      gap: spacing.xs,
                      backgroundColor: "rgba(255,255,255,0.07)",
                    }}
                  >
                    {isLoading ? (
                      <ActivityIndicator size="small" color="#8e8e93" />
                    ) : (
                      <>
                        <AppIcon icon={RepeatIcon} size={15} color="#8e8e93" />
                        <Text
                          style={{ fontSize: fontSize.sm, color: "#8e8e93" }}
                        >
                          Regenerate
                        </Text>
                      </>
                    )}
                  </Pressable>

                  <Pressable
                    onPress={handleUsePrompt}
                    style={{
                      flex: 1,
                      borderRadius: 12,
                      paddingVertical: spacing.md,
                      alignItems: "center",
                      justifyContent: "center",
                      flexDirection: "row",
                      gap: spacing.xs,
                      backgroundColor: "rgba(167,139,250,0.15)",
                    }}
                  >
                    <AppIcon icon={Tick02Icon} size={15} color="#a78bfa" />
                    <Text
                      style={{
                        fontSize: fontSize.sm,
                        fontWeight: "600",
                        color: "#a78bfa",
                      }}
                    >
                      Use This
                    </Text>
                  </Pressable>
                </View>
              </View>
            )}
          </BottomSheetScrollView>
        </BottomSheet.Content>
      </BottomSheet.Portal>
    </BottomSheet>
  );
});

GeneratePromptSheet.displayName = "GeneratePromptSheet";
