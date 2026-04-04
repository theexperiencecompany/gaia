import { Chip } from "@heroui/chip";
import { Alert01Icon } from "@icons";
import React, { useId } from "react";
import type { ToolDataEntry, ToolName } from "@/config/registries/toolRegistry";
import ThinkingBubble from "@/features/chat/components/bubbles/bot/ThinkingBubble";
import { getEmojiCount, isOnlyEmojis } from "@/features/chat/utils/emojiUtils";
import { splitMessageByBreaks } from "@/features/chat/utils/messageBreakUtils";
import { shouldShowTextBubble } from "@/features/chat/utils/messageContentUtils";
import { parseThinkingFromText } from "@/features/chat/utils/thinkingParser";
import type { ChatBubbleBotProps } from "@/types/features/chatBubbleTypes";
import type { TodoProgressData } from "@/types/features/todoProgressTypes";
import MarkdownRenderer from "../../../interface/MarkdownRenderer";
import TodoProgressSection from "../TodoProgressSection";
import UnifiedToolThread from "../UnifiedToolThread";
import { getTypedData, renderTool, type ToolDataUnion } from "./ToolRenderers";
import { useSubagentSynthesis } from "./useSubagentSynthesis";

const REPLY_QUOTE_MAX_LENGTH = 40;

/** Inline reply quote shown at the top of a bot bubble, scrolls to the original message on click. */
function ReplyQuote({
  replyToMessage,
}: {
  replyToMessage: { id: string; content: string; role: "user" | "assistant" };
}) {
  const truncated =
    replyToMessage.content.length > REPLY_QUOTE_MAX_LENGTH
      ? `${replyToMessage.content.slice(0, REPLY_QUOTE_MAX_LENGTH).trim()}...`
      : replyToMessage.content;

  return (
    <button
      type="button"
      className="-mx-5 mb-2 flex w-[calc(100%+40px)] cursor-pointer items-start rounded-md border-l-2 border-zinc-400 bg-zinc-700/50 py-1.5 pl-2.5 pr-3 text-left"
      onClick={() => {
        const el = document.getElementById(replyToMessage.id);
        if (el) {
          el.scrollIntoView({ behavior: "smooth", block: "center" });
          el.style.transition = "all 0.3s ease";
          el.style.scale = "1.02";
          setTimeout(() => {
            el.style.scale = "1";
          }, 300);
        }
      }}
    >
      <div className="flex flex-col overflow-hidden">
        <span className="text-[11px] font-semibold text-zinc-400">
          {replyToMessage.role === "user" ? "You" : "GAIA"}
        </span>
        <span className="truncate text-[12px] text-zinc-500">{truncated}</span>
      </div>
    </button>
  );
}

export default function TextBubble({
  text,
  disclaimer,
  tool_data,
  isConvoSystemGenerated,
  systemPurpose,
  loading,
  replyToMessage,
}: ChatBubbleBotProps) {
  const baseId = useId();

  // Parse thinking content from text
  const parsedContent = React.useMemo(() => {
    return parseThinkingFromText(text?.toString() || "");
  }, [text]);

  // Separate tool_calls_data + subagent_group from other tool_data entries.
  // The former are merged into a single UnifiedToolThread component.
  const { unifiedToolCalls, unifiedSubagentGroups, processedTools } =
    useSubagentSynthesis(tool_data);

  return (
    <>
      {parsedContent.thinking && (
        <ThinkingBubble thinkingContent={parsedContent.thinking} />
      )}

      {/* Unified tool thread — merges tool_calls_data + subagent_group */}
      {(unifiedToolCalls.length > 0 || unifiedSubagentGroups.length > 0) && (
        <UnifiedToolThread
          key={`${baseId}-unified-tools`}
          tool_calls={unifiedToolCalls}
          subagent_groups={unifiedSubagentGroups}
        />
      )}

      {processedTools.map((entry, index) => {
        const toolName = entry.tool_name as ToolName;
        const keyId = (entry as ToolDataEntry).timestamp || index;

        if (toolName === "todo_progress") {
          const data = getTypedData(entry as ToolDataUnion, "todo_progress");
          return data ? (
            <React.Fragment key={`${baseId}-tool-${toolName}-${keyId}`}>
              <TodoProgressSection
                todo_progress={data as TodoProgressData}
                isStreaming={loading}
              />
            </React.Fragment>
          ) : null;
        }

        const typedData = getTypedData(entry as ToolDataUnion, toolName);
        if (!typedData) return null;

        const toolCallId =
          typeof typedData === "object" &&
          typedData !== null &&
          "tool_call_id" in typedData
            ? String(
                (typedData as unknown as { tool_call_id?: string })
                  .tool_call_id ?? "",
              )
            : "";
        const toolKey = toolCallId
          ? `${baseId}-tool-${toolName}-${toolCallId}`
          : `${baseId}-tool-${toolName}-${index}`;

        return (
          <React.Fragment key={toolKey}>
            {renderTool(toolName, typedData, index)}
          </React.Fragment>
        );
      })}

      {shouldShowTextBubble(text, isConvoSystemGenerated, systemPurpose) &&
        (() => {
          // Use cleaned text without thinking tags
          const displayText = parsedContent.cleanText || "";
          const textParts = splitMessageByBreaks(displayText);
          // const hasMultipleParts = textParts.length > 1;

          const renderBubbleContent = (
            content: string,
            showDisclaimer: boolean,
          ) => (
            <div className="flex flex-col gap-3">
              <MarkdownRenderer content={content} isStreaming={loading} />
              {!!disclaimer && showDisclaimer && (
                <Chip
                  className="text-xs font-medium text-warning-500"
                  color="warning"
                  size="sm"
                  startContent={
                    <Alert01Icon className="text-warning-500" height={17} />
                  }
                  variant="flat"
                >
                  {disclaimer}
                </Chip>
              )}
            </div>
          );

          return (
            <div className="flex flex-col">
              {textParts.map((part, index) => {
                const isFirst = index === 0;
                const isLast = index === textParts.length - 1;
                const isSingle = textParts.length === 1;

                // Emoji detection for this specific part
                const isEmojiOnly = isOnlyEmojis(part);
                const emojiCount = isEmojiOnly ? getEmojiCount(part) : 0;

                // Single message should show tail (use last styling)
                // Otherwise: first = no tail, middle = no tail, last = show tail
                let groupedClasses = isSingle
                  ? "imessage-grouped-last"
                  : isFirst
                    ? "imessage-grouped-first mb-1.5"
                    : isLast
                      ? "imessage-grouped-last"
                      : "imessage-grouped-middle mb-1.5";

                let bubbleClassName = "imessage-bubble imessage-from-them";

                // Construct styles for emoji-only messages
                let textClass = "";

                if (isEmojiOnly) {
                  if (emojiCount === 1) {
                    bubbleClassName = "select-none";
                    groupedClasses = "";
                    textClass = "text-[4rem] leading-none";
                  } else if (emojiCount === 2) {
                    textClass = "text-5xl";
                  } else if (emojiCount === 3) {
                    textClass = "text-4xl";
                  }
                }

                return (
                  <div
                    // biome-ignore lint/suspicious/noArrayIndexKey: array is stable
                    key={`${baseId}-text-part-${index}`}
                    className={`${bubbleClassName} ${groupedClasses}`}
                  >
                    {/* Reply quote: full-width card with left accent border, scrolls to original on click */}
                    {isFirst && replyToMessage?.content && (
                      <ReplyQuote replyToMessage={replyToMessage} />
                    )}
                    <div className={textClass}>
                      {renderBubbleContent(part, isLast)}
                    </div>
                  </div>
                );
              })}
            </div>
          );
        })()}
    </>
  );
}
