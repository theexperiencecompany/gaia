import { Pressable, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { AppIcon, Cancel01Icon } from "@/components/icons";
import { Text } from "@/components/ui/text";

export interface UndoState {
  kind: "delete" | "complete";
  message: string;
  onUndo: () => void | Promise<void>;
}

interface TodoUndoToastProps {
  undo: UndoState | null;
  onDismiss: () => void;
}

/**
 * Lightweight in-app undo toast pinned above the bottom safe-area inset.
 * Holds for 5 seconds (managed by the parent), tap "Undo" to invoke
 * the recorded reversal action.
 */
export function TodoUndoToast({ undo, onDismiss }: TodoUndoToastProps) {
  const insets = useSafeAreaInsets();
  if (!undo) return null;
  return (
    <View
      pointerEvents="box-none"
      style={{
        position: "absolute",
        left: 16,
        right: 16,
        bottom: insets.bottom + 76,
      }}
    >
      <View
        style={{
          flexDirection: "row",
          alignItems: "center",
          gap: 12,
          paddingHorizontal: 14,
          paddingVertical: 12,
          borderRadius: 16,
          backgroundColor: "rgba(39,39,42,0.95)",
        }}
      >
        <Text
          style={{
            flex: 1,
            fontSize: 13,
            color: "#f4f4f5",
            fontWeight: "500",
          }}
          numberOfLines={1}
        >
          {undo.message}
        </Text>
        <Pressable
          onPress={() => {
            void undo.onUndo();
            onDismiss();
          }}
          hitSlop={8}
          style={{
            paddingHorizontal: 10,
            paddingVertical: 4,
            borderRadius: 12,
            backgroundColor: "rgba(0,187,255,0.18)",
          }}
        >
          <Text style={{ fontSize: 12, fontWeight: "600", color: "#00bbff" }}>
            Undo
          </Text>
        </Pressable>
        <Pressable onPress={onDismiss} hitSlop={8}>
          <AppIcon icon={Cancel01Icon} size={14} color="#71717a" />
        </Pressable>
      </View>
    </View>
  );
}
