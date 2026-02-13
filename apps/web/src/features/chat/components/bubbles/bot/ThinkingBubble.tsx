import { Brain02Icon } from "@icons";
import { useState } from "react";

interface ThinkingBubbleProps {
  thinkingContent: string;
}

export default function ThinkingBubble({
  thinkingContent,
}: ThinkingBubbleProps) {
  const [isExpanded, setIsExpanded] = useState(false);

  if (!thinkingContent) return null;

  return (
    <div className="mb-3 flex flex-col gap-2">
      <button
        type="button"
        onClick={() => setIsExpanded(!isExpanded)}
        className="group flex w-fit cursor-pointer items-center gap-2 text-sm text-zinc-500 transition-colors hover:text-zinc-700 dark:text-zinc-400 dark:hover:text-zinc-200"
        aria-label={
          isExpanded ? "Hide thinking process" : "Show thinking process"
        }
      >
        <Brain02Icon
          className="transition-all duration-200 group-hover:scale-110"
          size={16}
        />
        <span className="font-medium">
          {isExpanded ? "Hide thinking" : "Show thinking"}
        </span>
      </button>

      {isExpanded && (
        <div className="rounded-lg bg-zinc-100/80 px-4 py-3 dark:bg-zinc-800/80">
          <div className="text-sm leading-relaxed whitespace-pre-wrap text-zinc-700 dark:text-zinc-300">
            {thinkingContent}
          </div>
        </div>
      )}
    </div>
  );
}
