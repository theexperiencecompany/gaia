import { useState } from "react";
import {
  KeyboardAvoidingView,
  Modal,
  Platform,
  Pressable,
  TextInput,
  View,
} from "react-native";
import { AppIcon, Cancel01Icon, Folder02Icon } from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";

const PRESET_COLORS = [
  "#16c1ff",
  "#8b5cf6",
  "#10b981",
  "#f59e0b",
  "#ef4444",
  "#ec4899",
];

interface CreateProjectModalProps {
  visible: boolean;
  onClose: () => void;
  onCreated: (data: { name: string; color?: string }) => Promise<void>;
}

export function CreateProjectModal({
  visible,
  onClose,
  onCreated,
}: CreateProjectModalProps) {
  const { spacing, fontSize } = useResponsive();
  const [name, setName] = useState("");
  const [selectedColor, setSelectedColor] = useState<string>(PRESET_COLORS[0]);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const canSubmit = name.trim().length > 0 && !isSubmitting;

  const handleSubmit = async () => {
    if (!canSubmit) return;
    setIsSubmitting(true);
    try {
      await onCreated({ name: name.trim(), color: selectedColor });
      setName("");
      setSelectedColor(PRESET_COLORS[0]);
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleClose = () => {
    setName("");
    setSelectedColor(PRESET_COLORS[0]);
    onClose();
  };

  return (
    <Modal
      visible={visible}
      animationType="slide"
      presentationStyle="pageSheet"
      onRequestClose={handleClose}
    >
      <KeyboardAvoidingView
        behavior={Platform.OS === "ios" ? "padding" : "height"}
        style={{ flex: 1, backgroundColor: "#171920" }}
      >
        {/* Header */}
        <View
          style={{
            flexDirection: "row",
            alignItems: "center",
            justifyContent: "space-between",
            paddingHorizontal: spacing.md,
            paddingTop: spacing.lg,
            paddingBottom: spacing.md,
            borderBottomWidth: 1,
            borderBottomColor: "rgba(255,255,255,0.07)",
          }}
        >
          <Pressable onPress={handleClose} hitSlop={12}>
            <AppIcon icon={Cancel01Icon} size={20} color="#71717a" />
          </Pressable>

          <Text
            style={{
              fontSize: fontSize.base,
              fontWeight: "600",
              color: "#f4f4f5",
            }}
          >
            New Project
          </Text>

          <Pressable
            onPress={() => void handleSubmit()}
            disabled={!canSubmit}
            hitSlop={12}
            style={{
              borderRadius: 8,
              paddingHorizontal: spacing.md,
              paddingVertical: 7,
              backgroundColor: canSubmit
                ? "rgba(22,193,255,0.15)"
                : "rgba(255,255,255,0.03)",
            }}
          >
            <Text
              style={{
                fontSize: fontSize.sm,
                fontWeight: "600",
                color: canSubmit ? "#16c1ff" : "#3f3f46",
              }}
            >
              {isSubmitting ? "Creating..." : "Create"}
            </Text>
          </Pressable>
        </View>

        <View style={{ padding: spacing.md, gap: spacing.lg }}>
          {/* Preview */}
          <View
            style={{
              alignItems: "center",
              paddingVertical: spacing.lg,
            }}
          >
            <View
              style={{
                width: 64,
                height: 64,
                borderRadius: 16,
                backgroundColor: `${selectedColor}20`,
                alignItems: "center",
                justifyContent: "center",
                borderWidth: 2,
                borderColor: `${selectedColor}40`,
              }}
            >
              <AppIcon icon={Folder02Icon} size={28} color={selectedColor} />
            </View>
            {name.trim().length > 0 && (
              <Text
                style={{
                  marginTop: spacing.sm,
                  fontSize: fontSize.base,
                  fontWeight: "600",
                  color: "#f4f4f5",
                }}
              >
                {name.trim()}
              </Text>
            )}
          </View>

          {/* Name input */}
          <View style={{ gap: spacing.xs }}>
            <Text
              style={{
                fontSize: fontSize.xs,
                color: "#52525b",
                textTransform: "uppercase",
                letterSpacing: 0.8,
                fontWeight: "500",
              }}
            >
              Project Name
            </Text>
            <TextInput
              value={name}
              onChangeText={setName}
              placeholder="e.g. Work, Personal, Side project..."
              placeholderTextColor="#3f3f46"
              autoFocus
              style={{
                fontSize: fontSize.base,
                color: "#f4f4f5",
                backgroundColor: "rgba(255,255,255,0.04)",
                borderRadius: 12,
                paddingHorizontal: spacing.md,
                paddingVertical: spacing.md,
                borderWidth: 1,
                borderColor: "rgba(255,255,255,0.07)",
              }}
            />
          </View>

          {/* Color picker */}
          <View style={{ gap: spacing.sm }}>
            <Text
              style={{
                fontSize: fontSize.xs,
                color: "#52525b",
                textTransform: "uppercase",
                letterSpacing: 0.8,
                fontWeight: "500",
              }}
            >
              Color
            </Text>
            <View
              style={{
                flexDirection: "row",
                gap: spacing.md,
                flexWrap: "wrap",
              }}
            >
              {PRESET_COLORS.map((color) => {
                const isSelected = selectedColor === color;
                return (
                  <Pressable
                    key={color}
                    onPress={() => setSelectedColor(color)}
                    style={{
                      width: 40,
                      height: 40,
                      borderRadius: 20,
                      backgroundColor: color,
                      alignItems: "center",
                      justifyContent: "center",
                      borderWidth: isSelected ? 3 : 0,
                      borderColor: "#f4f4f5",
                      opacity: isSelected ? 1 : 0.7,
                    }}
                  />
                );
              })}
            </View>
          </View>
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );
}
