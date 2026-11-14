import type { Reaction } from "@gaia/shared/api/generated";
import { Chip } from "heroui-native";
import { type StyleProp, View, type ViewStyle } from "react-native";
import { cn } from "@/lib/utils";

/**
 * GAIA's emoji reaction pill below a user message, the mobile half of web's
 * MessageReactions. Outside the bubble, never inside it.
 */
export function MessageReactions({
  reaction,
  align,
  style,
}: {
  reaction: Reaction | null | undefined;
  align: "start" | "end";
  style?: StyleProp<ViewStyle>;
}) {
  if (!reaction) return null;

  return (
    <View
      style={style}
      className={cn(
        "flex-row flex-wrap gap-1",
        align === "end" ? "justify-end" : "justify-start",
      )}
    >
      <Chip
        size="sm"
        variant="soft"
        color="default"
        animation="disable-all"
        className="bg-zinc-800"
      >
        <Chip.Label>{reaction.emoji}</Chip.Label>
      </Chip>
    </View>
  );
}
