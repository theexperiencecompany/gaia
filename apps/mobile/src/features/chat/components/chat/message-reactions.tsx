import { groupReactions, type ReactionBadge } from "@gaia/shared/utils";
import { Chip } from "heroui-native";
import { type StyleProp, View, type ViewStyle } from "react-native";
import { cn } from "@/lib/utils";

/**
 * Emoji reaction pills below a message, one per emoji with its count — the
 * mobile half of web's MessageReactions. Outside the bubble, never inside it.
 */
export function MessageReactions({
  reactions,
  align,
  style,
}: {
  reactions: ReactionBadge[] | null | undefined;
  align: "start" | "end";
  style?: StyleProp<ViewStyle>;
}) {
  if (!reactions?.length) return null;

  return (
    <View
      style={style}
      className={cn(
        "flex-row flex-wrap gap-1",
        align === "end" ? "justify-end" : "justify-start",
      )}
    >
      {groupReactions(reactions).map(({ emoji, count }) => (
        <Chip
          key={emoji}
          size="sm"
          variant="soft"
          color="default"
          animation="disable-all"
          className="bg-zinc-800"
        >
          <Chip.Label>{emoji}</Chip.Label>
          {count > 1 && (
            <Chip.Label className="text-zinc-400">{count}</Chip.Label>
          )}
        </Chip>
      ))}
    </View>
  );
}
