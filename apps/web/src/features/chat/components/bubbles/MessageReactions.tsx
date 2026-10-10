import { groupReactions } from "@shared/utils";
import type { MessageReaction } from "@/config/registries/baseMessageRegistry";
import { cn } from "@/lib/utils";

interface MessageReactionsProps {
  reactions: MessageReaction[];
  align?: "start" | "end";
}

/**
 * Slack-style emoji reaction pills anchored to a message.
 *
 * Rendered OUTSIDE the message bubble (below it), never inside: the bubble
 * background is zinc-800 and the pills need contrast against the canvas.
 * Same-emoji acks collapse into one pill with a count.
 */
export function MessageReactions({
  reactions,
  align = "start",
}: MessageReactionsProps) {
  if (reactions.length === 0) return null;

  return (
    <div
      className={cn(
        "flex flex-wrap gap-1 pt-1",
        align === "end" ? "justify-end" : "justify-start",
      )}
    >
      {groupReactions(reactions).map(({ emoji, count }) => (
        <span
          key={emoji}
          className="inline-flex items-center gap-1 rounded-full border border-zinc-700 bg-zinc-900 px-2 py-0.5 text-sm leading-none select-none"
        >
          <span>{emoji}</span>
          {count > 1 && <span className="text-xs text-zinc-400">{count}</span>}
        </span>
      ))}
    </div>
  );
}
