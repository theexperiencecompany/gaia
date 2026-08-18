import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import { Alert01Icon, RedoIcon } from "@icons";
import {
  APPROVAL_REQUEST_TOOL_NAME,
  type ApprovalRequestData,
} from "@shared/chat";
import { parseOpenUISegments, splitMessageByBreaks } from "@shared/utils";
import * as m from "motion/react-m";
import dynamic from "next/dynamic";
import React, { useId } from "react";
import ThinkingBubble from "@/features/chat/components/bubbles/bot/ThinkingBubble";
import { getEmojiCount, isOnlyEmojis } from "@/features/chat/utils/emojiUtils";
import {
  MESSAGE_BREAK_DURATION_SECONDS,
  MESSAGE_BREAK_EASE_OUT_QUART,
  MESSAGE_BREAK_STAGGER_SECONDS,
} from "@/features/chat/utils/messageBreakUtils";
import { shouldShowTextBubble } from "@/features/chat/utils/messageContentUtils";
import { parseThinkingFromText } from "@/features/chat/utils/thinkingParser";
import { db } from "@/lib/db/chatDb";
import type { ChatBubbleBotProps } from "@/types/features/chatBubbleTypes";
import MarkdownRenderer from "../../../interface/MarkdownRenderer";
import {
  ApprovalResolveProvider,
  type ApprovalResolver,
} from "../ApprovalResolveContext";
import TodoProgressSection from "../TodoProgressSection";
import UnifiedToolThread from "../UnifiedToolThread";
import { getTypedData, renderTool, type ToolDataUnion } from "./ToolRenderers";
import { useSubagentSynthesis } from "./useSubagentSynthesis";
import { useToolRenderAudit } from "./useToolRenderAudit";

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

/**
 * The failure surface for a bot turn, in two shapes:
 *  - `partial` — some text streamed before the turn died, so a bubble already
 *    rendered above; this is a compact strip under it saying it was cut short.
 *  - full bubble — nothing streamed, so this IS the message.
 *
 * Retry lives here rather than only in the hover actions row: that row is
 * invisible until hover and suppressed on the last bubble while the
 * conversation is busy, which is exactly when a failure appears.
 */
function FailedResponse({
  error,
  partial,
  onRetry,
  isRetrying,
}: Readonly<{
  error: string;
  partial: boolean;
  onRetry?: () => void;
  isRetrying?: boolean;
}>) {
  const retryButton = onRetry && (
    <Button
      className="h-7 min-w-0 shrink-0 px-2 text-xs"
      isDisabled={isRetrying}
      onPress={onRetry}
      radius="full"
      size="sm"
      startContent={
        <div className={isRetrying ? "animate-spin" : ""}>
          <RedoIcon height={13} width={13} />
        </div>
      }
      variant="flat"
    >
      Retry
    </Button>
  );

  if (partial) {
    return (
      <div className="mt-1 flex items-center gap-2 text-zinc-400">
        <Alert01Icon className="shrink-0" height={15} width={15} />
        <span className="text-xs">Response was cut short</span>
        {retryButton}
      </div>
    );
  }

  return (
    <div className="imessage-bubble imessage-from-them imessage-grouped-last">
      <div className="flex items-start gap-2">
        <Alert01Icon
          className="mt-0.5 shrink-0 text-zinc-400"
          height={17}
          width={17}
        />
        <div className="flex flex-col items-start gap-1.5">
          <div className="flex flex-col gap-0.5">
            <span className="text-sm text-zinc-200">This response failed</span>
            <span className="line-clamp-2 text-xs text-zinc-400">{error}</span>
          </div>
          {retryButton}
        </div>
      </div>
    </div>
  );
}

type PartTransition = {
  duration: number;
  ease: typeof MESSAGE_BREAK_EASE_OUT_QUART;
  delay: number;
};

/** Bubble body: markdown plus an optional disclaimer chip on the last block. */
function BubbleContent({
  content,
  showDisclaimer,
  disclaimer,
  isStreaming,
}: Readonly<{
  content: string;
  showDisclaimer: boolean;
  disclaimer: ChatBubbleBotProps["disclaimer"];
  isStreaming: ChatBubbleBotProps["loading"];
}>) {
  return (
    <div className="flex flex-col gap-3">
      <MarkdownRenderer content={content} isStreaming={isStreaming} />
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
}

/** Resolve grouping + emoji-scaling classes for a pure-markdown bubble. */
function resolveMarkdownBubbleStyles({
  isSingle,
  isLast,
  isFirst,
  isEmojiOnly,
  emojiCount,
}: {
  isSingle: boolean;
  isLast: boolean;
  isFirst: boolean;
  isEmojiOnly: boolean;
  emojiCount: number;
}): { bubbleClassName: string; groupedClasses: string; textClass: string } {
  // Single message shows tail (last styling); otherwise first = no tail,
  // middle = no tail, last = show tail.
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

  return { bubbleClassName, groupedClasses, textClass };
}

interface TextPartProps {
  isFirst: boolean;
  isLast: boolean;
  isSingle: boolean;
  baseId: string;
  originalIndex: number;
  loading: ChatBubbleBotProps["loading"];
  disclaimer: ChatBubbleBotProps["disclaimer"];
  replyToMessage: ChatBubbleBotProps["replyToMessage"];
  partTransition: PartTransition;
}

/** Pure-markdown part — normal iMessage bubble. */
function MarkdownPartBubble({
  part,
  isFirst,
  isLast,
  isSingle,
  loading,
  disclaimer,
  replyToMessage,
  partTransition,
}: Readonly<TextPartProps & { part: string }>) {
  const isEmojiOnly = isOnlyEmojis(part);
  const emojiCount = isEmojiOnly ? getEmojiCount(part) : 0;
  const { bubbleClassName, groupedClasses, textClass } =
    resolveMarkdownBubbleStyles({
      isSingle,
      isLast,
      isFirst,
      isEmojiOnly,
      emojiCount,
    });

  return (
    <m.div
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
        <BubbleContent
          content={part}
          showDisclaimer={isLast}
          disclaimer={disclaimer}
          isStreaming={loading}
        />
      </div>
    </m.div>
  );
}

/** Mixed part: OpenUI segments render OUTSIDE the bubble. */
function MixedPart({
  segments,
  isFirst,
  isLast,
  baseId,
  originalIndex,
  loading,
  disclaimer,
  replyToMessage,
  partTransition,
}: Readonly<
  TextPartProps & { segments: ReturnType<typeof parseOpenUISegments> }
>) {
  const lastMdIdx = segments.reduce(
    (acc, s, i) => (s.type === "markdown" && s.content.trim() ? i : acc),
    -1,
  );

  return (
    <m.div
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
            {isFirst && segIdx === 0 && replyToMessage?.content && (
              <ReplyQuote replyToMessage={replyToMessage} />
            )}
            <BubbleContent
              content={seg.content}
              showDisclaimer={isLastMdInLastPart}
              disclaimer={disclaimer}
              isStreaming={loading}
            />
          </div>
        );
      })}
    </m.div>
  );
}

export default function TextBubble({
  message_id,
  text,
  disclaimer,
  tool_data,
  isConvoSystemGenerated,
  systemPurpose,
  loading,
  replyToMessage,
  error,
  onRetry,
  isRetrying,
}: Readonly<ChatBubbleBotProps>) {
  const baseId = useId();

  // Persist a HIL approval decision into THIS message's tool_data, so the pending
  // card becomes a settled receipt (clearing the derived "Waiting for approval"
  // pill) and survives reload. The resolved frame is published on the resumed
  // run's stream — a different message — so it never reaches this card otherwise.
  const resolveApproval = React.useCallback<ApprovalResolver>(
    (approvalId, resolved) => {
      if (!message_id || !tool_data) return;
      const next = tool_data.map((entry) =>
        entry.tool_name === APPROVAL_REQUEST_TOOL_NAME &&
        (entry.data as ApprovalRequestData | null)?.approval_id === approvalId
          ? { ...entry, data: resolved }
          : entry,
      );
      void db.updateMessage(message_id, { tool_data: next });
    },
    [message_id, tool_data],
  );

  // Parse thinking content from text
  const parsedContent = React.useMemo(() => {
    return parseThinkingFromText(text?.toString() || "");
  }, [text]);

  // Single ordered timeline of tool calls + subagent groups (emission order)
  // and the remaining tool_data entries that render via TOOL_RENDERERS.
  const { timeline, processedTools } = useSubagentSynthesis(tool_data);

  // Dev-only: record what this bubble did with each tool_data entry.
  useToolRenderAudit(message_id, tool_data);

  // Tool calls currently blocked on a HIL approval, keyed by the shared
  // tool_call_id. Lets the tool row/subagent show "Waiting for approval"
  // instead of a generic spinner while the approval card handles the decision.
  const pendingApprovalToolCallIds = React.useMemo(() => {
    const ids = new Set<string>();
    tool_data?.forEach((entry) => {
      if (entry.tool_name !== APPROVAL_REQUEST_TOOL_NAME) return;
      const data = entry.data as ApprovalRequestData | null;
      if (data?.status === "pending" && data.tool_call_id) {
        ids.add(data.tool_call_id);
      }
    });
    return ids;
  }, [tool_data]);

  // Settled decisions, keyed the same way — the tool's own row in the thread
  // carries the outcome as a chip instead of a separate receipts block.
  const approvalStatusByToolCallId = React.useMemo(() => {
    const statuses = new Map<string, ApprovalRequestData["status"]>();
    tool_data?.forEach((entry) => {
      if (entry.tool_name !== APPROVAL_REQUEST_TOOL_NAME) return;
      const data = entry.data as ApprovalRequestData | null;
      if (data?.tool_call_id && data.status !== "pending") {
        statuses.set(data.tool_call_id, data.status);
      }
    });
    return statuses;
  }, [tool_data]);

  return (
    <ApprovalResolveProvider value={resolveApproval}>
      {parsedContent.thinking && (
        <ThinkingBubble thinkingContent={parsedContent.thinking} />
      )}

      {timeline.length > 0 && (
        <UnifiedToolThread
          key={`${baseId}-unified-tools`}
          timeline={timeline}
          isStreaming={!!loading}
          pendingApprovalToolCallIds={pendingApprovalToolCallIds}
          approvalStatusByToolCallId={approvalStatusByToolCallId}
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
          const textParts = splitMessageByBreaks(displayText);

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
                const partKey = `${baseId}-text-part-${originalIndex}`;
                const partTransition: PartTransition = {
                  duration: MESSAGE_BREAK_DURATION_SECONDS,
                  ease: MESSAGE_BREAK_EASE_OUT_QUART,
                  delay: visibleIndex * MESSAGE_BREAK_STAGGER_SECONDS,
                };

                return hasOpenUI ? (
                  <MixedPart
                    key={partKey}
                    segments={segments}
                    isFirst={isFirst}
                    isLast={isLast}
                    isSingle={isSingle}
                    baseId={baseId}
                    originalIndex={originalIndex}
                    loading={loading}
                    disclaimer={disclaimer}
                    replyToMessage={replyToMessage}
                    partTransition={partTransition}
                  />
                ) : (
                  <MarkdownPartBubble
                    key={partKey}
                    part={part}
                    isFirst={isFirst}
                    isLast={isLast}
                    isSingle={isSingle}
                    baseId={baseId}
                    originalIndex={originalIndex}
                    loading={loading}
                    disclaimer={disclaimer}
                    replyToMessage={replyToMessage}
                    partTransition={partTransition}
                  />
                );
              })}
            </div>
          );
        })()}

      {/* Every errored turn surfaces its failure and a retry. With no text this
          IS the message (a quiet error bubble, so reloads don't show an empty
          one); with partial text it's a strip under the bubble that already
          rendered, marking the answer as truncated rather than finished. */}
      {!!error && (
        <FailedResponse
          error={error}
          isRetrying={isRetrying}
          onRetry={onRetry}
          partial={
            shouldShowTextBubble(text, isConvoSystemGenerated, systemPurpose) ||
            !!parsedContent.cleanText.trim()
          }
        />
      )}
    </ApprovalResolveProvider>
  );
}
