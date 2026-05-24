import type { Workflow } from "@gaia/shared/types";
import { ActivityIndicator, Pressable, View } from "react-native";
import {
  AppIcon,
  FlashIcon,
  MagicWand01Icon,
  PlayIcon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { selectionHaptic } from "@/lib/haptics";
import { useTodoWorkflow } from "../../hooks/use-todo-workflow";

interface TodoWorkflowSectionProps {
  todoId: string;
  onRunWorkflow?: (workflow: Workflow) => void;
}

/**
 * Mobile workflow section for the todo detail sheet.
 *
 * States: idle (button to generate) → generating (skeleton + spinner) →
 * has workflow (step list + Run button). WS-driven via shared
 * `WORKFLOW_WS_EVENTS`, with a polling fallback in `useTodoWorkflow`.
 */
export function TodoWorkflowSection({
  todoId,
  onRunWorkflow,
}: TodoWorkflowSectionProps) {
  const { workflow, isGenerating, error, generate } = useTodoWorkflow(todoId);
  const hasWorkflow = !!workflow;

  return (
    <View style={{ gap: 8 }}>
      <View
        style={{
          flexDirection: "row",
          alignItems: "center",
          gap: 8,
          paddingHorizontal: 4,
        }}
      >
        <AppIcon icon={FlashIcon} size={14} color="#a1a1aa" />
        <Text
          style={{
            fontSize: 11,
            fontWeight: "600",
            color: "#71717a",
            letterSpacing: 0.6,
            textTransform: "uppercase",
            flex: 1,
          }}
        >
          Suggested Workflow
        </Text>
        {isGenerating ? (
          <View style={{ flexDirection: "row", alignItems: "center", gap: 4 }}>
            <ActivityIndicator size="small" color="#00bbff" />
            <Text style={{ fontSize: 11, color: "#00bbff" }}>Generating</Text>
          </View>
        ) : null}
      </View>

      <View
        style={{
          backgroundColor: "rgba(39,39,42,0.30)",
          borderRadius: 16,
          padding: 14,
          gap: 12,
        }}
      >
        {isGenerating ? (
          <View style={{ gap: 10 }}>
            {[0, 1, 2].map((i) => (
              <View
                key={i}
                style={{
                  flexDirection: "row",
                  alignItems: "center",
                  gap: 10,
                }}
              >
                <View
                  style={{
                    width: 22,
                    height: 22,
                    borderRadius: 11,
                    backgroundColor: "rgba(255,255,255,0.06)",
                  }}
                />
                <View style={{ flex: 1, gap: 6 }}>
                  <View
                    style={{
                      height: 11,
                      borderRadius: 4,
                      backgroundColor: "rgba(255,255,255,0.06)",
                      width: "70%",
                    }}
                  />
                  <View
                    style={{
                      height: 9,
                      borderRadius: 4,
                      backgroundColor: "rgba(255,255,255,0.04)",
                      width: "50%",
                    }}
                  />
                </View>
              </View>
            ))}
          </View>
        ) : hasWorkflow && workflow ? (
          <View style={{ gap: 10 }}>
            {workflow.steps.map((step, idx) => (
              <View
                key={step.id}
                style={{
                  flexDirection: "row",
                  alignItems: "flex-start",
                  gap: 10,
                }}
              >
                <View
                  style={{
                    width: 22,
                    height: 22,
                    borderRadius: 11,
                    backgroundColor: "rgba(0,187,255,0.15)",
                    alignItems: "center",
                    justifyContent: "center",
                  }}
                >
                  <Text
                    style={{
                      fontSize: 11,
                      fontWeight: "600",
                      color: "#00bbff",
                    }}
                  >
                    {idx + 1}
                  </Text>
                </View>
                <View style={{ flex: 1, gap: 2 }}>
                  <Text
                    style={{
                      fontSize: 13,
                      fontWeight: "500",
                      color: "#f4f4f5",
                    }}
                  >
                    {step.title}
                  </Text>
                  {step.description ? (
                    <Text style={{ fontSize: 12, color: "#a1a1aa" }}>
                      {step.description}
                    </Text>
                  ) : null}
                </View>
              </View>
            ))}
            {onRunWorkflow ? (
              <Pressable
                onPress={() => {
                  selectionHaptic();
                  onRunWorkflow(workflow);
                }}
                style={({ pressed }) => ({
                  marginTop: 4,
                  flexDirection: "row",
                  alignItems: "center",
                  justifyContent: "center",
                  gap: 6,
                  paddingVertical: 10,
                  borderRadius: 12,
                  backgroundColor: pressed
                    ? "rgba(34,197,94,0.20)"
                    : "rgba(34,197,94,0.12)",
                })}
              >
                <AppIcon icon={PlayIcon} size={14} color="#22c55e" />
                <Text
                  style={{ fontSize: 13, fontWeight: "600", color: "#22c55e" }}
                >
                  Run workflow
                </Text>
              </Pressable>
            ) : null}
          </View>
        ) : (
          <View style={{ alignItems: "center", gap: 10, paddingVertical: 8 }}>
            <AppIcon icon={MagicWand01Icon} size={26} color="#52525b" />
            <Text
              style={{ fontSize: 13, color: "#a1a1aa", textAlign: "center" }}
            >
              {error ? "Generation failed. Try again?" : "No workflow yet"}
            </Text>
            <Pressable
              onPress={() => {
                selectionHaptic();
                void generate();
              }}
              style={({ pressed }) => ({
                flexDirection: "row",
                alignItems: "center",
                gap: 6,
                paddingHorizontal: 14,
                paddingVertical: 9,
                borderRadius: 12,
                backgroundColor: pressed
                  ? "rgba(0,187,255,0.20)"
                  : "rgba(0,187,255,0.15)",
              })}
            >
              <AppIcon icon={MagicWand01Icon} size={14} color="#00bbff" />
              <Text
                style={{ fontSize: 13, fontWeight: "600", color: "#00bbff" }}
              >
                {error ? "Retry" : "Generate workflow"}
              </Text>
            </Pressable>
            <Text
              style={{
                fontSize: 11,
                color: "#52525b",
                textAlign: "center",
                paddingHorizontal: 12,
              }}
            >
              AI will draft a step-by-step plan to complete this task.
            </Text>
          </View>
        )}
      </View>
    </View>
  );
}
