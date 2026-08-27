import {
  SUBAGENT_GROUP_TOOL_NAME,
  TOOL_CALLS_DATA_TOOL_NAME,
} from "@gaia/shared/chat";
import {
  parseOpenUISegments,
  parseThinkingFromText,
  splitMessageByBreaks,
} from "@gaia/shared/utils";
import * as Haptics from "expo-haptics";
import { PressableFeedback } from "heroui-native";
import { useCallback, useMemo } from "react";
import { Text, View } from "react-native";
import Animated, { FadeIn } from "react-native-reanimated";
import { MessageBubble } from "@/components/ui/message-bubble";
import { useResponsive } from "@/lib/responsive";
import { extractUrls, useLinkPreview } from "../../hooks/use-link-preview";
import { ToolDataRenderer } from "../../tool-data/renderers";
import type { Message } from "../../types";
import { OpenUIRenderer } from "../openui/OpenUIRenderer";
import { ActivityBlock } from "../streaming/activity-block";
import { buildTimeline } from "../streaming/activity-format";
import { FailedResponse } from "./failed-response";
import { FollowUpActions } from "./follow-up-actions";
import { ImageBubble } from "./image-bubble";
import { LinkPreviewCard } from "./link-preview-card";
import { MemoryIndicator } from "./memory-indicator";
import type { MessageActionConfig } from "./message-action-sheet";
import { MessageReplyQuote } from "./message-reply-quote";
import { ThinkingBubble } from "./thinking-bubble";

const EMOJI_ONLY_REGEX = /^[\u{1F000}-\u{1FFFF}\u{2600}-\u{27BF}\s]+$/u;

/** Shape accepted by MemoryIndicator, derived from the component itself. */
type MemoryIndicatorData = Parameters<typeof MemoryIndicator>[0]["memoryData"];

// Gap scale token (decisions §5).
const GAP_SM = 4;

function getEmojiInfo(text: string): { isEmojiOnly: boolean; count: number } {
  const trimmed = text.trim();
  if (!EMOJI_ONLY_REGEX.test(trimmed)) return { isEmojiOnly: false, count: 0 };
  const chars = [...trimmed.replace(/\s/g, "")];
  return { isEmojiOnly: true, count: chars.length };
}

// -- ChatMessage --------------------------------------------------------------

interface ChatMessageProps {
  message: Message;
  onFollowUpAction?: (action: string) => void;
  onReply?: (message: Message) => void;
  onLongPress?: (config: MessageActionConfig) => void;
  /** Re-run this failed turn (wired to useChat.retryLastMessage). */
  onRetry?: () => void;
  isLoading?: boolean;
  isLastMessage?: boolean;
  loadingMessage?: string;
  progressToolName?: string | null;
  progressMessage?: string | null;
}

type BubbleGrouping = "none" | "first" | "last" | "middle";

/** Grouping position for a bubble within a list of `total` parts. */
function bubbleGrouping(index: number, total: number): BubbleGrouping {
  if (total === 1) return "none";
  if (index === 0) return "first";
  if (index === total - 1) return "last";
  return "middle";
}

/** Font size for an emoji-only message, or null when it should render as text. */
function emojiFontSize(count: number): number | null {
  if (count === 1) return 52;
  if (count === 2) return 40;
  if (count === 3) return 32;
  return null;
}

/** Long-press handler shared by the sent and received message layouts. */
function useMessageLongPress(
  message: Message,
  onLongPress?: (config: MessageActionConfig) => void,
  onReply?: (message: Message) => void,
) {
  return useCallback(() => {
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    if (onLongPress) {
      onLongPress({
        messageId: message.id,
        conversationId: (message.metadata?.conversation_id as string) ?? "",
        content: message.text ?? "",
        isUser: message.isUser,
        isPinned: message.metadata?.is_pinned as boolean | undefined,
      });
    } else {
      onReply?.(message);
    }
  }, [onLongPress, onReply, message]);
}

interface MessagePart {
  part: string;
  index: number;
}

function useMessageParts(text: string | undefined): {
  parsedContent: ReturnType<typeof parseThinkingFromText>;
  messageParts: MessagePart[];
} {
  // Strip <thinking> tags from raw text so they are never rendered in the bubble.
  const parsedContent = useMemo(
    () => parseThinkingFromText(text ?? ""),
    [text],
  );
  const messageParts = splitMessageByBreaks(parsedContent.cleanText)
    .filter(Boolean)
    .map((part, index) => ({ part, index }));
  return { parsedContent, messageParts };
}

/** A single sent (user) message part: emoji-only text or a bubble. */
function SentMessagePart({
  part,
  index,
  total,
}: {
  part: string;
  index: number;
  total: number;
}) {
  const { isEmojiOnly, count } = getEmojiInfo(part);
  if (isEmojiOnly && total === 1) {
    const emojiSize = emojiFontSize(count);
    if (emojiSize) {
      return (
        <Text style={{ fontSize: emojiSize, lineHeight: emojiSize + 8 }}>
          {part}
        </Text>
      );
    }
  }
  return (
    <MessageBubble
      message={part}
      variant="sent"
      grouped={bubbleGrouping(index, total)}
    />
  );
}

interface ChatMessageLayoutProps {
  message: Message;
  handleLongPress: () => void;
}

function UserChatMessage({
  message,
  handleLongPress,
  messageParts,
}: ChatMessageLayoutProps & { messageParts: MessagePart[] }) {
  const { spacing } = useResponsive();

  return (
    <Animated.View entering={FadeIn.duration(200)}>
      <PressableFeedback
        onLongPress={handleLongPress}
        onPressIn={() => Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light)}
        delayLongPress={350}
        style={{
          flexDirection: "row",
          marginBottom: spacing.xs,
          alignItems: "flex-end",
          justifyContent: "flex-end",
          paddingHorizontal: spacing.md,
        }}
      >
        <View
          style={{ flexDirection: "column", gap: spacing.xs, maxWidth: "80%" }}
        >
          {message.replyToMessage && (
            <MessageReplyQuote
              replyToMessage={message.replyToMessage}
              isUserMessage={true}
            />
          )}
          {messageParts.map(({ part, index }) => (
            <SentMessagePart
              key={`${message.id}-${index}`}
              part={part}
              index={index}
              total={messageParts.length}
            />
          ))}
        </View>
      </PressableFeedback>
    </Animated.View>
  );
}

/** The received (AI) message text/OpenUI parts — accumulates WHILE streaming. */
function AITextParts({
  parts,
  messageId,
  isLoading,
  isLastMessage,
}: {
  parts: MessagePart[];
  messageId: string;
  isLoading: boolean;
  isLastMessage: boolean;
}) {
  const { spacing } = useResponsive();

  return (
    <>
      {parts.map(({ part, index: partIndex }) => {
        const segments = parseOpenUISegments(part, isLoading);
        const grouped = bubbleGrouping(partIndex, parts.length);

        return segments.map((segment, segIndex) => {
          const key = `${messageId}-${partIndex}-${segIndex}`;
          const isLastSegmentOfLastPart =
            partIndex === parts.length - 1 && segIndex === segments.length - 1;
          const showCursor =
            isLoading && isLastMessage && isLastSegmentOfLastPart;

          if (segment.type === "openui") {
            return (
              <View
                key={key}
                style={{ paddingHorizontal: spacing.md, width: "100%" }}
              >
                <OpenUIRenderer
                  code={segment.content}
                  isStreaming={!segment.isComplete}
                />
              </View>
            );
          }
          return (
            <MessageBubble
              key={key}
              message={segment.content}
              variant="received"
              grouped={grouped}
              isStreaming={showCursor}
            />
          );
        });
      })}
    </>
  );
}

interface AIMainContentProps {
  message: Message;
  messageParts: MessagePart[];
  isGeneratingImage: boolean;
  isLoading: boolean;
  isLastMessage: boolean;
}

/**
 * Main content area of an AI message. Streaming activity lives in the
 * ActivityBlock sibling ABOVE this — text accumulates simultaneously instead
 * of the old mutually-exclusive surface swap (thinking OR progress OR text).
 */
function AIMainContent({
  message,
  messageParts,
  isGeneratingImage,
  isLoading,
  isLastMessage,
}: AIMainContentProps) {
  const { spacing } = useResponsive();

  if (message.imageData || isGeneratingImage) {
    return (
      <View style={{ paddingHorizontal: spacing.md, width: "100%" }}>
        <ImageBubble
          imageData={message.imageData ?? { url: "", prompt: "" }}
          isGenerating={isGeneratingImage}
          caption={
            messageParts.length > 0
              ? messageParts.map(({ part }) => part).join(" ")
              : undefined
          }
        />
      </View>
    );
  }
  if (messageParts.length > 0) {
    return (
      <AITextParts
        parts={messageParts}
        messageId={message.id}
        isLoading={isLoading}
        isLastMessage={isLastMessage}
      />
    );
  }
  return null;
}

function AIChatMessage({
  message,
  handleLongPress,
  parsedContent,
  messageParts,
  isLoading,
  isLastMessage,
  loadingMessage,
  progressMessage,
  onFollowUpAction,
  onRetry,
}: ChatMessageLayoutProps & {
  parsedContent: ReturnType<typeof parseThinkingFromText>;
  messageParts: MessagePart[];
  isLoading: boolean;
  isLastMessage: boolean;
  /** Contextual loading label from the screen ("Thinking about X..."). */
  loadingMessage: string;
  progressMessage: string | null;
  onFollowUpAction?: (action: string) => void;
  /** Re-run the failed turn (only meaningful when message.error is set). */
  onRetry?: () => void;
}) {
  const { spacing } = useResponsive();

  const hasStreamedText =
    messageParts.length > 0 || !!parsedContent.thinking || !!message.imageData;
  const isGeneratingImage = message.imageData != null && !message.imageData.url;
  const failed = !!message.error && !isLoading;

  const hasActivity = useMemo(
    () => buildTimeline(message.toolData).length > 0,
    [message.toolData],
  );

  // Tool data that carries its own rich typed card (approvals, weather, …).
  // tool_calls_data and subagent_group render inside the ActivityBlock chain
  // instead — subagent_group has no typed card and would hit UnsupportedToolCard.
  const nonCallToolData = useMemo(
    () =>
      (message.toolData ?? []).filter(
        (e) =>
          e.tool_name !== TOOL_CALLS_DATA_TOOL_NAME &&
          e.tool_name !== SUBAGENT_GROUP_TOOL_NAME,
      ),
    [message.toolData],
  );

  const rawText = message.text ?? "";
  const linkPreviewUrls = extractUrls(rawText);
  const { data: linkPreviewData } = useLinkPreview(
    !isLoading && rawText.length > 0 ? rawText : "",
  );

  const hasAnyContent =
    hasStreamedText ||
    hasActivity ||
    isLoading ||
    isGeneratingImage ||
    nonCallToolData.length > 0 ||
    !!message.memoryData ||
    !!message.followUpActions?.length ||
    !!message.error;

  if (!hasAnyContent) return null;

  return (
    <Animated.View entering={FadeIn.duration(200)}>
      <PressableFeedback
        onLongPress={handleLongPress}
        onPressIn={() => Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light)}
        delayLongPress={350}
        style={{
          flexDirection: "column",
          marginBottom: spacing.sm,
          alignItems: "flex-start",
          width: "100%",
        }}
      >
        {/* Agent activity — persistent first sibling of the turn; streamed
            markdown accumulates BELOW it simultaneously (decisions §2). */}
        {(hasActivity || isLoading) && (
          <ActivityBlock
            toolData={message.toolData ?? []}
            isRunning={isLoading}
            hasStreamedText={hasStreamedText}
            failed={failed}
            thinkingLabel={
              progressMessage ??
              (loadingMessage !== "Thinking..." ? loadingMessage : null)
            }
          />
        )}

        {/* Typed tool-data cards (non tool_calls_data) — full width above text */}
        {nonCallToolData.length ? (
          <View style={{ paddingHorizontal: spacing.md, alignSelf: "stretch" }}>
            <ToolDataRenderer toolData={nonCallToolData} />
          </View>
        ) : null}

        {/* Thinking / reasoning bubble (collapsible) */}
        {parsedContent.thinking ? (
          <View style={{ paddingHorizontal: spacing.md, marginBottom: GAP_SM }}>
            <ThinkingBubble thinkingContent={parsedContent.thinking} />
          </View>
        ) : null}

        {/* Main message content — full width, no avatar (mobile space constraint) */}
        <AIMainContent
          message={message}
          messageParts={messageParts}
          isGeneratingImage={isGeneratingImage}
          isLoading={isLoading}
          isLastMessage={isLastMessage}
        />

        {/* Link preview – shown below message content for AI messages */}
        {!isLoading && linkPreviewUrls.length > 0 && linkPreviewData?.length ? (
          <View style={{ paddingHorizontal: spacing.md, marginTop: GAP_SM }}>
            <LinkPreviewCard
              url={linkPreviewData[0].url}
              title={linkPreviewData[0].title}
              description={linkPreviewData[0].description}
              imageUrl={linkPreviewData[0].imageUrl}
              favicon={linkPreviewData[0].favicon}
              domain={linkPreviewData[0].domain}
            />
          </View>
        ) : null}

        {/* Memory indicator pill */}
        {message.memoryData ? (
          <MemoryIndicator
            memoryData={message.memoryData as MemoryIndicatorData}
          />
        ) : null}

        {/* Follow-up action chips */}
        {message.followUpActions?.length ? (
          <FollowUpActions
            actions={message.followUpActions}
            onActionPress={onFollowUpAction}
          />
        ) : null}

        {/* Errored turn: keep the streamed text above and mark the failure */}
        {message.error && failed ? (
          <FailedResponse
            error={message.error}
            hasPartialText={messageParts.length > 0}
            onRetry={onRetry}
          />
        ) : null}
      </PressableFeedback>
    </Animated.View>
  );
}

export function ChatMessage({
  message,
  onFollowUpAction,
  onReply,
  onLongPress,
  onRetry,
  isLoading = false,
  isLastMessage = false,
  loadingMessage = "Thinking...",
  progressMessage = null,
}: ChatMessageProps) {
  const { parsedContent, messageParts } = useMessageParts(message.text);
  const handleLongPress = useMessageLongPress(message, onLongPress, onReply);

  if (message.isUser) {
    return (
      <UserChatMessage
        message={message}
        handleLongPress={handleLongPress}
        messageParts={messageParts}
      />
    );
  }

  return (
    <AIChatMessage
      message={message}
      handleLongPress={handleLongPress}
      parsedContent={parsedContent}
      messageParts={messageParts}
      isLoading={isLoading}
      isLastMessage={isLastMessage}
      loadingMessage={loadingMessage}
      progressMessage={progressMessage}
      onFollowUpAction={onFollowUpAction}
      onRetry={onRetry}
    />
  );
}
