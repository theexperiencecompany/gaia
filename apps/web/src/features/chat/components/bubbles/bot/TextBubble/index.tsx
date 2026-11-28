import { Chip } from "@heroui/react";
import { Alert01Icon, RedoIcon } from "@icons";
import {
  APPROVAL_REQUEST_TOOL_NAME,
  type ApprovalRequestData,
} from "@shared/chat";
import { cardData } from "@shared/conversation";
import * as m from "motion/react-m";
import React, { useId } from "react";
import { GaiaButton } from "@/components/shared/GaiaButton";
import { getEmojiCount, isOnlyEmojis } from "@/features/chat/utils/emojiUtils";
import {
  DEFAULT_PART_CHOREOGRAPHY,
  MESSAGE_BREAK_EASE_OUT_QUART,
  type PartChoreography,
} from "@/features/chat/utils/messageBreakUtils";
import { shouldShowTextBubble } from "@/features/chat/utils/messageContentUtils";
import type { ChatBubbleBotProps } from "@/types/features/chatBubbleTypes";
import MarkdownRenderer from "../../../interface/MarkdownRenderer";
import { RichContentRenderer } from "../../../interface/RichContentRenderer";
import { ChatItemBoundary } from "../ChatItemBoundary";
import { StoppedNote } from "../StoppedNote";
import type { ApprovalReceipt } from "../SubagentRow";
import TodoProgressSection from "../TodoProgressSection";
import UnifiedToolThread, { type TimelineItem } from "../UnifiedToolThread";
import { getTypedData, renderTool } from "./ToolRenderers";
import { useToolRenderAudit } from "./useToolRenderAudit";

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
          el.scrollIntoView({ behavior: "smooth", block: "center" });
          el.style.transition = "scale 0.3s ease";
          el.style.scale = "1.02";
          setTimeout(() => {
            el.style.scale = "1";
          }, 300);
        }
      }}
    >
      <span
        aria-hidden
        className="absolute inset-y-2 left-1.5 w-1 rounded-full bg-zinc-400 transition-colors group-hover/quote:bg-accent"
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
 * The failure surface for a bot turn: `partial` is a compact strip under an
 * already-streamed bubble carrying the server's failure line; otherwise this IS the
 * message.
 *
 * Retry lives here (not only the hover row), since that row is invisible
 * until hover and suppressed on the last bubble exactly when a failure appears.
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
    <GaiaButton
      shape="pill"
      inset="tight"
      className="h-7 min-w-0 shrink-0 text-xs"
      isDisabled={isRetrying}
      onPress={onRetry}
      size="sm"
      variant="default-soft"
    >
      <div className={isRetrying ? "animate-spin" : ""}>
        <RedoIcon height={13} width={13} />
      </div>
      Retry
    </GaiaButton>
  );

  if (partial) {
    return (
      <div className="mt-1 flex items-center gap-2 text-zinc-400">
        <Alert01Icon className="shrink-0" height={15} width={15} />
        <span className="text-xs">{error}</span>
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
        <Chip color="warning" size="sm" variant="soft">
          <Alert01Icon className="text-warning-500" height={17} />
          <Chip.Label className="text-xs font-medium">{disclaimer}</Chip.Label>
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
  part,
  isFirst,
  isLast,
  loading,
  disclaimer,
  replyToMessage,
  partTransition,
}: Readonly<TextPartProps & { part: string }>) {
  return (
    <m.div
      className="flex flex-col"
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={partTransition}
    >
      <RichContentRenderer
        content={part}
        isStreaming={loading}
        renderMarkdown={(seg, segIdx, isLastMarkdown) => {
          const isLastMdInLastPart = isLast && isLastMarkdown;
          return (
            <div
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
        }}
      />
    </m.div>
  );
}

const NO_BUBBLES: readonly string[] = [];

export default function TextBubble({
  message_id,
  text,
  bubbles = NO_BUBBLES,
  timeline,
  disclaimer,
  isConvoSystemGenerated,
  systemPurpose,
  loading,
  replyToMessage,
  error,
  stopped,
  onRetry,
  isRetrying,
  partChoreography = DEFAULT_PART_CHOREOGRAPHY,
}: Readonly<ChatBubbleBotProps> & {
  partChoreography?: PartChoreography;
}) {
  const baseId = useId();

  const displayText = text?.toString() ?? "";

  // The server's timeline: the tool thread in emission order, then the cards
  // that render on their own, each under a key stable across the stream.
  const steps = (timeline?.steps ?? []) as readonly TimelineItem[];
  const cards = timeline?.cards ?? [];

  // Every approval the item asked for, as the server grouped them into one card.
  const approvals = React.useMemo(
    () =>
      (timeline
        ? cardData(timeline, APPROVAL_REQUEST_TOOL_NAME)
        : []) as (ApprovalRequestData | null)[],
    [timeline],
  );

  // Dev-only: record what this bubble did with each card of the timeline.
  useToolRenderAudit(message_id, timeline);

  // Tool calls currently blocked on a HIL approval, keyed by the shared
  // tool_call_id. Lets the tool row/subagent show "Waiting for approval"
  // instead of a generic spinner while the approval card handles the decision.
  const pendingApprovalToolCallIds = React.useMemo(() => {
    const ids = new Set<string>();
    for (const data of approvals) {
      if (data?.status === "waiting" && data.tool_call_id) {
        ids.add(data.tool_call_id);
      }
    }
    return ids;
  }, [approvals]);

  // Settled decisions, keyed the same way — the tool's row carries the outcome
  // as a chip, with feedback so it shows the receipt, not just "Approved".
  const { approvalOutcomeByToolCallId } = React.useMemo(() => {
    const outcomes = new Map<string, ApprovalReceipt>();
    for (const data of approvals) {
      if (data?.tool_call_id && data.status !== "waiting") {
        outcomes.set(data.tool_call_id, {
          status: data.status,
          decider: data.decider ?? null,
          action: data.action ?? null,
          feedback: data.feedback ?? null,
        });
      }
    }
    return { approvalOutcomeByToolCallId: outcomes };
  }, [approvals]);

  return (
    <>
      {steps.length > 0 && (
        <ChatItemBoundary
          key={`${baseId}-unified-tools`}
          item="tool_thread"
          messageId={message_id}
          resetKey={steps}
        >
          <UnifiedToolThread
            timeline={steps}
            isStreaming={!!loading}
            pendingApprovalToolCallIds={pendingApprovalToolCallIds}
            approvalOutcomeByToolCallId={approvalOutcomeByToolCallId}
          />
        </ChatItemBoundary>
      )}

      {cards.map(({ key: entryKey, card }, index) => {
        const toolName = card.tool_name;

        if (toolName === "todo_progress") {
          const data = getTypedData(card, "todo_progress");
          return data ? (
            <ChatItemBoundary
              key={`${baseId}-tool-${entryKey}`}
              item={toolName}
              messageId={message_id}
              resetKey={data}
            >
              <TodoProgressSection todo_progress={data} isStreaming={loading} />
            </ChatItemBoundary>
          ) : null;
        }

        const typedData = getTypedData(card, toolName);
        if (!typedData) return null;

        return (
          <ChatItemBoundary
            key={`${baseId}-tool-${entryKey}`}
            item={toolName}
            messageId={message_id}
            resetKey={typedData}
          >
            {renderTool(toolName, typedData, index)}
          </ChatItemBoundary>
        );
      })}

      {shouldShowTextBubble(text, isConvoSystemGenerated, systemPurpose) &&
        // Mid-stream a reply can have no bubbles yet, which would flash an empty bubble + tail.
        bubbles.length > 0 &&
        (() => {
          const textParts = bubbles;

          // Single pass so first/last/single reflect the *visible* list, not
          // array index — else a visible part sandwiched between blanks loses
          // its tail. Animation delay uses visible index; original index is kept for React keys.
          const visibleParts: Array<{ part: string; originalIndex: number }> =
            [];
          for (const [originalIndex, part] of textParts.entries()) {
            if (!part.trim()) continue;
            visibleParts.push({ part, originalIndex });
          }

          if (visibleParts.length === 0) return null;

          return (
            <ChatItemBoundary
              item="text"
              messageId={message_id}
              resetKey={bubbles}
            >
              <div className="flex flex-col">
                {visibleParts.map(({ part, originalIndex }, visibleIndex) => {
                  const isFirst = visibleIndex === 0;
                  const isLast = visibleIndex === visibleParts.length - 1;
                  const isSingle = visibleParts.length === 1;
                  const hasOpenUI = part.includes(":::openui");
                  const partKey = `${baseId}-text-part-${originalIndex}`;
                  const partTransition: PartTransition = {
                    duration: partChoreography.durationSeconds,
                    ease: MESSAGE_BREAK_EASE_OUT_QUART,
                    delay: visibleIndex * partChoreography.staggerSeconds,
                  };

                  return hasOpenUI ? (
                    <MixedPart
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
            </ChatItemBoundary>
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
            !!displayText.trim()
          }
        />
      )}
      {stopped && !error && <StoppedNote />}
    </>
  );
}
