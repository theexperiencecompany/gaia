import { Pressable, TextInput, View } from "react-native";
import { Add01Icon, AppIcon, Delete02Icon } from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import type { WorkflowStep } from "../types/workflow-types";

interface WorkflowStepsEditorProps {
  steps: WorkflowStep[];
  onChange: (steps: WorkflowStep[]) => void;
}

function generateId(): string {
  return Math.random().toString(36).slice(2, 10);
}

export function WorkflowStepsEditor({
  steps,
  onChange,
}: WorkflowStepsEditorProps) {
  const { spacing, fontSize, moderateScale } = useResponsive();

  const addStep = () => {
    const newStep: WorkflowStep = {
      id: generateId(),
      title: "",
      category: "",
      description: "",
    };
    onChange([...steps, newStep]);
  };

  const updateStep = (
    index: number,
    field: keyof WorkflowStep,
    value: string,
  ) => {
    const updated = steps.map((step, i) =>
      i === index ? { ...step, [field]: value } : step,
    );
    onChange(updated);
  };

  const deleteStep = (index: number) => {
    onChange(steps.filter((_, i) => i !== index));
  };

  return (
    <View style={{ gap: spacing.sm }}>
      <Text style={{ fontSize: fontSize.xs, color: "#8a9099" }}>Steps</Text>

      {steps.map((step, index) => (
        <View
          key={step.id}
          style={{
            backgroundColor: "#1c1c1e",
            borderRadius: moderateScale(12, 0.5),
            padding: spacing.md,
            gap: spacing.sm,
          }}
        >
          <View
            style={{
              flexDirection: "row",
              alignItems: "center",
              gap: spacing.sm,
            }}
          >
            <View
              style={{
                width: 28,
                height: 28,
                borderRadius: 14,
                backgroundColor: "#3f3f46",
                alignItems: "center",
                justifyContent: "center",
              }}
            >
              <Text
                style={{
                  fontSize: fontSize.xs,
                  fontWeight: "700",
                  color: "#a1a1aa",
                }}
              >
                {index + 1}
              </Text>
            </View>
            <TextInput
              style={{
                flex: 1,
                fontSize: fontSize.sm,
                color: "#fff",
                paddingVertical: spacing.xs,
              }}
              placeholder="Step name"
              placeholderTextColor="#555"
              value={step.title}
              onChangeText={(v) => updateStep(index, "title", v)}
              maxLength={100}
            />
            <Pressable
              onPress={() => deleteStep(index)}
              hitSlop={8}
              style={({ pressed }) => ({
                opacity: pressed ? 0.5 : 1,
                padding: spacing.xs,
              })}
            >
              <AppIcon icon={Delete02Icon} size={18} color="#71717a" />
            </Pressable>
          </View>

          <TextInput
            style={{
              fontSize: fontSize.xs,
              color: "#a1a1aa",
              paddingVertical: spacing.xs,
              borderTopWidth: 1,
              borderTopColor: "#2c2c2e",
              paddingTop: spacing.sm,
            }}
            placeholder="Description (optional)"
            placeholderTextColor="#444"
            value={step.description}
            onChangeText={(v) => updateStep(index, "description", v)}
            multiline
            maxLength={500}
          />
        </View>
      ))}

      <Pressable
        onPress={addStep}
        style={({ pressed }) => ({
          flexDirection: "row",
          alignItems: "center",
          justifyContent: "center",
          gap: spacing.sm,
          borderWidth: 1,
          borderStyle: "dashed",
          borderColor: pressed ? "#00bbff" : "#3f3f46",
          borderRadius: moderateScale(12, 0.5),
          paddingVertical: spacing.md,
          backgroundColor: pressed ? "rgba(0,187,255,0.05)" : "transparent",
        })}
      >
        <AppIcon icon={Add01Icon} size={16} color="#00bbff" />
        <Text
          style={{ fontSize: fontSize.sm, color: "#00bbff", fontWeight: "500" }}
        >
          Add step
        </Text>
      </Pressable>
    </View>
  );
}
