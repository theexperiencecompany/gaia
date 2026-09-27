import { groupReactions, type ReactionBadge } from "@gaia/shared/utils";
import { Chip } from "heroui-native";
import { View } from "react-native";
import { cn } from "@/lib/utils";

/**
 * Emoji reaction pills below a message, one per emoji with its count — the
 * mobile half of web's MessageReactions. Outside the bubble, never inside it.
 */
export function MessageReactions({
  reactions,
  align,
}: {
  reactions: ReactionBadge[];
  align: "start" | "end";
}) {
  if (reactions.length === 0) return null;

  return (
    <View
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
