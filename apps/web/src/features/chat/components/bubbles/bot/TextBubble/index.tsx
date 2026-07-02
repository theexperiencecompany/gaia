import { Chip } from "@heroui/chip";
import { Alert01Icon } from "@icons";
import {
  parseOpenUISegments,
  splitByBreaksPreservingFences,
} from "@shared/utils";
import * as m from "motion/react-m";
import dynamic from "next/dynamic";
import React, { useId } from "react";
import ThinkingBubble from "@/features/chat/components/bubbles/bot/ThinkingBubble";
import { getEmojiCount, isOnlyEmojis } from "@/features/chat/utils/emojiUtils";
import {
  MESSAGE_BREAK_DURATION_SECONDS,
  MESSAGE_BREAK_EASE_OUT_QUART,
  MESSAGE_BREAK_STAGGER_SECONDS,
  splitMessageByBreaks,
} from "@/features/chat/utils/messageBreakUtils";
import { shouldShowTextBubble } from "@/features/chat/utils/messageContentUtils";
import { parseThinkingFromText } from "@/features/chat/utils/thinkingParser";
import type { ChatBubbleBotProps } from "@/types/features/chatBubbleTypes";
import MarkdownRenderer from "../../../interface/MarkdownRenderer";
import TodoProgressSection from "../TodoProgressSection";
import UnifiedToolThread from "../UnifiedToolThread";
import { getTypedData, renderTool, type ToolDataUnion } from "./ToolRenderers";
import { useSubagentSynthesis } from "./useSubagentSynthesis";

// OpenUI components use bg-zinc-800 (same as the bubble) and must render
// OUTSIDE the imessage-bubble — see bubbles/bot/CLAUDE.md.
const OpenUIRenderer = dynamic(
  () => import("../../../interface/OpenUIRenderer"),
  { ssr: false },
);

const REPLY_QUOTE_MAX_LENGTH = 40;

/** Inline reply quote shown at the top of a bot bubble, scrolls to the original message on click. */
function ReplyQuote({
  replyToMessage,
}: Readonly<{
  replyToMessage: { id: string; content: string; role: "user" | "assistant" };
}>) {
  const truncated =
    replyToMessage.content.length > REPLY_QUOTE_MAX_LENGTH
      ? `${replyToMessage.content.slice(0, REPLY_QUOTE_MAX_LENGTH).trim()}...`
      : replyToMessage.content;

  return (
    <button
      type="button"
      className="group/quote relative -ml-2 mb-2 flex w-full cursor-pointer items-start rounded-xl bg-zinc-700/50 py-2 pl-4 pr-3 text-left transition-colors hover:bg-zinc-700"
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
      <span
        aria-hidden
        className="absolute inset-y-2 left-1.5 w-1 rounded-full bg-zinc-400 transition-colors group-hover/quote:bg-primary"
      />
      <div className="flex flex-col overflow-hidden">
        <span className="text-[11px] font-semibold text-zinc-400">
          {replyToMessage.role === "user" ? "You" : "GAIA"}
        </span>
        <span className="truncate text-[12px] text-zinc-500">{truncated}</span>
      </div>
    </button>
  );
}

/** Quiet failed-response bubble shown when a bot turn died with no text. */
function FailedResponse({ error }: Readonly<{ error: string }>) {
  return (
    <div className="imessage-bubble imessage-from-them imessage-grouped-last">
      <div className="flex items-start gap-2">
        <Alert01Icon
          className="mt-0.5 shrink-0 text-zinc-400"
          height={17}
          width={17}
        />
        <div className="flex flex-col gap-0.5">
          <span className="text-sm text-zinc-200">This response failed</span>
          <span className="line-clamp-2 text-xs text-zinc-400">{error}</span>
        </div>
      </div>
    </div>
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
  error,
}: Readonly<ChatBubbleBotProps>) {
  const baseId = useId();

  // Parse thinking content from text
  const parsedContent = React.useMemo(() => {
    return parseThinkingFromText(text?.toString() || "");
  }, [text]);

  // Single ordered timeline of tool calls + subagent groups (emission order)
  // and the remaining tool_data entries that render via TOOL_RENDERERS.
  const { timeline, processedTools } = useSubagentSynthesis(tool_data);

  return (
    <>
      {parsedContent.thinking && (
        <ThinkingBubble thinkingContent={parsedContent.thinking} />
      )}

      {timeline.length > 0 && (
        <UnifiedToolThread
          key={`${baseId}-unified-tools`}
          timeline={timeline}
          isStreaming={!!loading}
        />
      )}

      {processedTools.map((entry, index) => {
        const toolName = entry.tool_name;
        const keyId = entry.timestamp || index;

        if (toolName === "todo_progress") {
          const data = getTypedData(entry as ToolDataUnion, "todo_progress");
          return data ? (
            <React.Fragment key={`${baseId}-tool-${toolName}-${keyId}`}>
              <TodoProgressSection todo_progress={data} isStreaming={loading} />
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
        // Gate on the CLEANED display text, not raw `text`: during a slow start
        // the message can briefly hold non-visible content (thinking residue, a
        // stray char) while the rendered text is still empty, which would flash
        // an empty bubble + tail. No visible content → no bubble.
        parsedContent.cleanText.trim().length > 0 &&
        (() => {
          // Use cleaned text without thinking tags
          const displayText = parsedContent.cleanText || "";
          // Preserve :::openui fences when splitting so they aren't mangled.
          const textParts = displayText.includes(":::openui")
            ? splitByBreaksPreservingFences(displayText)
            : splitMessageByBreaks(displayText);

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

          // Filter empty/whitespace-only parts up front so first/last/single
          // reflect the *visible* list, not the array index. Without this, a
          // single visible part sandwiched between blanks (e.g. trailing break,
          // post-thinking residue) would lose its tail because `isLast` would
          // point at a non-rendered entry. Animation delays use the visible
          // index so blanks don't shift the stagger; the original index is kept
          // for keys to preserve React identity across re-renders.
          const visibleParts = textParts
            .map((part, originalIndex) => ({ part, originalIndex }))
            .filter(({ part }) => part.trim());

          if (visibleParts.length === 0) return null;

          return (
            <div className="flex flex-col">
              {visibleParts.map(({ part, originalIndex }, visibleIndex) => {
                const isFirst = visibleIndex === 0;
                const isLast = visibleIndex === visibleParts.length - 1;
                const isSingle = visibleParts.length === 1;
                const segments = parseOpenUISegments(part, !!loading);
                const hasOpenUI = segments.some((s) => s.type === "openui");
                const partTransition = {
                  duration: MESSAGE_BREAK_DURATION_SECONDS,
                  ease: MESSAGE_BREAK_EASE_OUT_QUART,
                  delay: visibleIndex * MESSAGE_BREAK_STAGGER_SECONDS,
                };

                // ── Pure markdown part — normal iMessage bubble ──
                if (!hasOpenUI) {
                  const isEmojiOnly = isOnlyEmojis(part);
                  const emojiCount = isEmojiOnly ? getEmojiCount(part) : 0;

                  // Single message shows tail (last styling); otherwise first =
                  // no tail, middle = no tail, last = show tail.
                  let groupedClasses: string;
                  if (isSingle || isLast) {
                    groupedClasses = "imessage-grouped-last";
                  } else if (isFirst) {
                    groupedClasses = "imessage-grouped-first mb-1.5";
                  } else {
                    groupedClasses = "imessage-grouped-middle mb-1.5";
                  }
                  let bubbleClassName = "imessage-bubble imessage-from-them";
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
                    <m.div
                      key={`${baseId}-text-part-${originalIndex}`}
                      className={`${bubbleClassName} ${groupedClasses}`}
                      initial={{ opacity: 0, y: 6 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={partTransition}
                    >
                      {/* Reply quote: full-width card, scrolls to original on click */}
                      {isFirst && replyToMessage?.content && (
                        <ReplyQuote replyToMessage={replyToMessage} />
                      )}
                      <div className={textClass}>
                        {renderBubbleContent(part, isLast)}
                      </div>
                    </m.div>
                  );
                }

                // ── Mixed part: OpenUI segments render OUTSIDE the bubble ──
                const lastMdIdx = segments.reduce(
                  (acc, s, i) =>
                    s.type === "markdown" && s.content.trim() ? i : acc,
                  -1,
                );

                return (
                  <m.div
                    key={`${baseId}-text-part-${originalIndex}`}
                    className="flex flex-col"
                    initial={{ opacity: 0, y: 6 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={partTransition}
                  >
                    {segments.map((seg, segIdx) => {
                      const segKey = `${baseId}-seg-${originalIndex}-${segIdx}`;
                      if (seg.type === "openui") {
                        return (
                          <OpenUIRenderer
                            key={segKey}
                            code={seg.content}
                            isStreaming={!!loading && !seg.isComplete}
                          />
                        );
                      }
                      if (!seg.content.trim()) return null;
                      const isLastMdInLastPart = isLast && segIdx === lastMdIdx;
                      return (
                        <div
                          key={segKey}
                          className={`imessage-bubble imessage-from-them ${isLastMdInLastPart ? "imessage-grouped-last" : "imessage-grouped-first"} mb-1.5`}
                        >
                          {isFirst &&
                            segIdx === 0 &&
                            replyToMessage?.content && (
                              <ReplyQuote replyToMessage={replyToMessage} />
                            )}
                          {renderBubbleContent(seg.content, isLastMdInLastPart)}
                        </div>
                      );
                    })}
                  </m.div>
                );
              })}
            </div>
          );
        })()}

      {/* Failed turn with no response text — render a quiet error bubble so
          reloads don't show an empty bubble. */}
      {!!error && !parsedContent.cleanText.trim() && (
        <FailedResponse error={error} />
      )}
    </>
  );
}
