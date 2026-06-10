import { Pressable, View } from "react-native";
import { AppIcon, MoreVerticalIcon, Tick02Icon } from "@/components/icons";

interface TodoRowTrailingProps {
  selectionMode: boolean;
  isSelected: boolean;
  onSelect: () => void;
  onMenu: () => void;
}

/**
 * Trailing slot of a todo row. In multi-select mode this becomes the
 * selection circle (filled #00bbff when selected). Otherwise it shows
 * an ellipsis menu opener.
 */
export function TodoRowTrailing({
  selectionMode,
  isSelected,
  onSelect,
  onMenu,
}: TodoRowTrailingProps) {
  if (selectionMode) {
    return (
      <Pressable
        onPress={onSelect}
        hitSlop={10}
        accessibilityRole="checkbox"
        accessibilityState={{ checked: isSelected }}
        style={{
          width: 24,
          height: 24,
          borderRadius: 12,
          alignItems: "center",
          justifyContent: "center",
          marginLeft: 8,
          backgroundColor: isSelected ? "#00bbff" : "transparent",
          borderWidth: isSelected ? 0 : 1.5,
          borderColor: "#52525b",
        }}
      >
        {isSelected ? (
          <AppIcon icon={Tick02Icon} size={14} color="#0a0a0a" />
        ) : null}
      </Pressable>
    );
  }

  return (
    <Pressable
      onPress={onMenu}
      hitSlop={10}
      accessibilityRole="button"
      accessibilityLabel="Open todo actions"
      style={{
        width: 28,
        height: 28,
        alignItems: "center",
        justifyContent: "center",
        marginLeft: 4,
      }}
    >
      <View>
        <AppIcon icon={MoreVerticalIcon} size={18} color="#71717a" />
      </View>
    </Pressable>
  );
}
