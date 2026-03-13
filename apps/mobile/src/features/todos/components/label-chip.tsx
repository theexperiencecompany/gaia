import { Pressable, View } from "react-native";
import { AppIcon, Tag01Icon } from "@/components/icons";
import { Text } from "@/components/ui/text";

function hashColor(label: string): string {
  const PALETTE = [
    "#16c1ff", // cyan
    "#a78bfa", // violet
    "#34d399", // emerald
    "#fb923c", // orange
    "#f472b6", // pink
    "#facc15", // yellow
    "#60a5fa", // blue
    "#4ade80", // green
    "#f87171", // red
    "#c084fc", // purple
  ];
  let hash = 0;
  for (let i = 0; i < label.length; i++) {
    hash = (hash * 31 + label.charCodeAt(i)) & 0xffffffff;
  }
  return PALETTE[Math.abs(hash) % PALETTE.length];
}

interface LabelChipProps {
  label: string;
  onPress?: (label: string) => void;
  size?: "sm" | "md";
}

export function LabelChip({ label, onPress, size = "sm" }: LabelChipProps) {
  const color = hashColor(label);
  const isSmall = size === "sm";

  const content = (
    <View
      style={{
        flexDirection: "row",
        alignItems: "center",
        backgroundColor: `${color}18`,
        borderRadius: 6,
        borderWidth: 1,
        borderColor: `${color}40`,
        paddingHorizontal: isSmall ? 7 : 10,
        paddingVertical: isSmall ? 3 : 5,
        gap: isSmall ? 4 : 5,
      }}
    >
      <AppIcon icon={Tag01Icon} size={isSmall ? 11 : 13} color={color} />
      <Text
        style={{
          fontSize: isSmall ? 11 : 13,
          color,
          fontWeight: "500",
        }}
      >
        {label.charAt(0).toUpperCase() + label.slice(1)}
      </Text>
    </View>
  );

  if (onPress) {
    return (
      <Pressable onPress={() => onPress(label)} hitSlop={4}>
        {content}
      </Pressable>
    );
  }

  return content;
}
