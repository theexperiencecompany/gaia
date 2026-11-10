import { ActivityIndicator, Pressable, View } from "react-native";
import {
  AppIcon,
  Comment01Icon,
  Delete02Icon,
  Tick02Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { impactHaptic } from "@/lib/haptics";
import { useConfirmDialog } from "@/shared/components/ui/app-confirm-dialog";

interface TodoDetailFooterProps {
  completed: boolean;
  onToggleComplete: () => void;
  onDelete: () => void;
  /** A tracked todo's "Open chat"; absent for a todo with no chat. */
  chat?: { onOpen: () => void; isOpening: boolean };
}

const ROUND_ACTION = {
  width: 44,
  height: 44,
  borderRadius: 22,
  alignItems: "center",
  justifyContent: "center",
} as const;

export function TodoDetailFooter({
  completed,
  onToggleComplete,
  onDelete,
  chat,
}: TodoDetailFooterProps) {
  const confirm = useConfirmDialog();
  const confirmDelete = async () => {
    const ok = await confirm({
      title: "Delete todo",
      message: "Delete this todo? This cannot be undone.",
      confirmLabel: "Delete",
      destructive: true,
    });
    if (!ok) return;
    impactHaptic("medium");
    onDelete();
  };

  return (
    <View
      className="flex-row items-center gap-3 px-5 py-3 border-t border-zinc-800"
      style={{ borderTopWidth: 1, borderTopColor: "rgba(63,63,70,0.5)" }}
    >
      <Pressable
        onPress={confirmDelete}
        hitSlop={8}
        accessibilityLabel="Delete todo"
        style={ROUND_ACTION}
      >
        <AppIcon icon={Delete02Icon} size={20} color="#71717a" />
      </Pressable>

      {chat ? (
        <Pressable
          onPress={chat.onOpen}
          disabled={chat.isOpening}
          hitSlop={8}
          accessibilityLabel="Open chat"
          style={{ ...ROUND_ACTION, backgroundColor: "rgba(63,63,70,0.6)" }}
        >
          {chat.isOpening ? (
            <ActivityIndicator size="small" color="#e4e4e7" />
          ) : (
            <AppIcon icon={Comment01Icon} size={20} color="#e4e4e7" />
          )}
        </Pressable>
      ) : null}

      <Pressable
        onPress={onToggleComplete}
        style={{
          flex: 1,
          height: 44,
          borderRadius: 16,
          alignItems: "center",
          justifyContent: "center",
          flexDirection: "row",
          gap: 8,
          backgroundColor: completed ? "rgba(63,63,70,0.6)" : "#00bbff",
        }}
      >
        <AppIcon
          icon={Tick02Icon}
          size={16}
          color={completed ? "#e4e4e7" : "#000"}
        />
        <Text
          style={{
            fontSize: 15,
            fontWeight: "600",
            color: completed ? "#e4e4e7" : "#000",
          }}
        >
          {completed ? "Mark incomplete" : "Mark complete"}
        </Text>
      </Pressable>
    </View>
  );
}
