import { Pressable, View } from "react-native";
import { AppIcon, Delete02Icon, Tick02Icon } from "@/components/icons";
import { Text } from "@/components/ui/text";
import { impactHaptic } from "@/lib/haptics";
import { useConfirmDialog } from "@/shared/components/ui/app-confirm-dialog";

interface TodoDetailFooterProps {
  completed: boolean;
  onToggleComplete: () => void;
  onDelete: () => void;
}

export function TodoDetailFooter({
  completed,
  onToggleComplete,
  onDelete,
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
        style={{
          width: 44,
          height: 44,
          borderRadius: 22,
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <AppIcon icon={Delete02Icon} size={20} color="#71717a" />
      </Pressable>

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
