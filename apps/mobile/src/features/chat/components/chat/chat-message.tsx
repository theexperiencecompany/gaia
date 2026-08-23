import {
  parseOpenUISegments,
  parseThinkingFromText,
  splitMessageByBreaks,
} from "@gaia/shared/utils";
import * as Haptics from "expo-haptics";
import { PressableFeedback } from "heroui-native";
import { useCallback, useMemo } from "react";
import { Pressable, View } from "react-native";
import Animated, { FadeIn, FadeInDown } from "react-native-reanimated";
import {
  Alert01Icon,
  AppIcon,
  Brain02Icon,
  RepeatIcon,
} from "@/components/icons";
import { MessageBubble } from "@/components/ui/message-bubble";
import { Text } from "@/components/ui/text";
import { ThinkingCard } from "@/features/chat/components/streaming/ThinkingCard";
import { ToolProgressCard } from "@/features/chat/components/streaming/ToolProgressCard";
import { useResponsive } from "@/lib/responsive";
import { extractUrls, useLinkPreview } from "../../hooks/use-link-preview";
import { ToolDataRenderer } from "../../tool-data/renderers";
import type { Message } from "../../types";
import { OpenUIRenderer } from "../openui/OpenUIRenderer";
import { ImageBubble } from "./image-bubble";
import { LinkPreviewCard } from "./link-preview-card";
import { LoadingIndicator } from "./loading-indicator";
import type { MessageActionConfig } from "./message-action-sheet";
import { MessageReplyQuote } from "./message-reply-quote";
import { ThinkingBubble } from "./thinking-bubble";

const EMOJI_ONLY_REGEX = /^[\u{1F000}-\u{1FFFF}\u{2600}-\u{27BF}\s]+$/u;

function getEmojiInfo(text: string): { isEmojiOnly: boolean; count: number } {
  const trimmed = text.trim();
  if (!EMOJI_ONLY_REGEX.test(trimmed)) return { isEmojiOnly: false, count: 0 };
  const chars = [...trimmed.replace(/\s/g, "")];
  return { isEmojiOnly: true, count: chars.length };
}

// -- Follow-up actions --------------------------------------------------------

interface FollowUpActionsProps {
  actions: string[];
  onActionPress?: (action: string) => void;
}

function FollowUpActions({ actions, onActionPress }: FollowUpActionsProps) {
  const { spacing } = useResponsive();
  if (!actions.length) return null;

  return (
    <View
      className="flex-row flex-wrap gap-2 mt-2"
      style={{ paddingLeft: spacing.md, paddingRight: spacing.md }}
    >
      {actions.map((action, i) => (
        <Animated.View
          key={action}
          entering={FadeInDown.delay(i * 60)
            .duration(300)
            .springify()}
        >
          <Pressable
            onPress={() => {
              Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
              onActionPress?.(action);
            }}
            className="px-3.5 py-1.5 rounded-full bg-zinc-800 active:bg-zinc-700"
          >
            <Text className="text-zinc-300 text-sm">{action}</Text>
          </Pressable>
        </Animated.View>
      ))}
    </View>
  );
}

// -- Memory indicator ---------------------------------------------------------

type MemoryDataShape = {
  type?: string;
  operation?: string;
  status?: string;
  count?: number;
  content?: string;
} | null;

function getMemoryLabel(memoryData: MemoryDataShape): string | null {
  if (!memoryData) return null;

  if (memoryData.type === "memory_stored") return "Memory stored";

  if (memoryData.status === "success") {
    switch (memoryData.operation) {
      case "create":
        return "Memory created";
      case "search":
        if (memoryData.count === 0) return "No memories found";
        if (memoryData.count === 1) return "Found 1 memory";
        return `Found ${memoryData.count} memories`;
      case "list":
        if (memoryData.count === 0) return "No memories";
        return `Retrieved ${memoryData.count} memories`;
      default:
        return "Memory updated";
    }
  }

  if (memoryData.status === "storing") return "Storing memory...";
  if (memoryData.status === "searching") return "Searching memories...";
  if (memoryData.status === "retrieving") return "Retrieving memories...";

  return null;
}

function MemoryIndicator({ memoryData }: { memoryData: MemoryDataShape }) {
  const { spacing, fontSize, moderateScale } = useResponsive();
  const label = getMemoryLabel(memoryData);
  if (!label) return null;

  return (
    <View
      style={{
        marginTop: spacing.xs + 2,
        paddingHorizontal: spacing.md,
      }}
    >
      <View
        style={{
          flexDirection: "row",
          alignItems: "center",
          alignSelf: "flex-start",
          gap: spacing.xs,
          backgroundColor: "rgba(63, 63, 70, 0.5)",
          borderRadius: moderateScale(12, 0.5),
          paddingHorizontal: spacing.sm + 2,
          paddingVertical: spacing.xs,
        }}
      >
        <AppIcon
          icon={Brain02Icon}
          size={moderateScale(11, 0.5)}
          color="#a1a1aa"
        />
        <Text
          style={{
            fontSize: fontSize.xs,
            color: "#a1a1aa",
            fontWeight: "500",
          }}
        >
          {label}
        </Text>
      </View>
    </View>
  );
}

// -- Failed response ----------------------------------------------------------

/**
 * Failure surface for an errored turn — mobile counterpart of web's
 * FailedResponse. The streamed text (if any) stays visible above; this strip
 * marks the answer as cut short and offers a retry.
 */
function FailedResponse({
  error,
  hasPartialText,
  onRetry,
}: {
  error: string;
  hasPartialText: boolean;
  onRetry?: () => void;
}) {
  const { spacing, fontSize, moderateScale } = useResponsive();

  if (hasPartialText) {
    // Compact strip under the partial bubble — the answer was truncated.
    return (
      <View
        style={{
          flexDirection: "row",
          alignItems: "center",
          gap: spacing.sm,
          marginTop: spacing.xs + 2,
          paddingHorizontal: spacing.md,
        }}
      >
        <AppIcon icon={Alert01Icon} size={14} color="#a1a1aa" />
        <Text
          style={{ color: "#a1a1aa", fontSize: fontSize.xs, flexShrink: 1 }}
        >
          Response was cut short
        </Text>
        {onRetry ? <RetryButton onRetry={onRetry} /> : null}
      </View>
    );
  }

  // Full bubble — nothing streamed, so this IS the message.
  return (
    <View style={{ paddingHorizontal: spacing.md, width: "100%" }}>
      <View
        style={{
          alignSelf: "flex-start",
          maxWidth: "85%",
          backgroundColor: "#27272a",
          borderRadius: moderateScale(20, 0.5),
          padding: spacing.md,
          flexDirection: "row",
          alignItems: "flex-start",
          gap: spacing.sm,
        }}
      >
        <AppIcon
          icon={Alert01Icon}
          size={17}
          color="#a1a1aa"
          style={{ marginTop: 1 }}
        />
        <View style={{ flexShrink: 1, gap: spacing.xs }}>
          <Text style={{ color: "#e4e4e7", fontSize: fontSize.base }}>
            This response failed
          </Text>
          <Text
            style={{ color: "#a1a1aa", fontSize: fontSize.sm }}
            numberOfLines={2}
          >
            {error}
          </Text>
          {onRetry ? <RetryButton onRetry={onRetry} /> : null}
        </View>
      </View>
    </View>
  );
}

function RetryButton({ onRetry }: { onRetry: () => void }) {
  const { moderateScale } = useResponsive();
  return (
    <Pressable
      onPress={onRetry}
      style={({ pressed }) => ({
        flexDirection: "row",
        alignItems: "center",
        gap: 4,
        opacity: pressed ? 0.7 : 1,
        borderRadius: moderateScale(12, 0.5),
        borderWidth: 0,
        paddingHorizontal: 8,
        paddingVertical: 4,
        alignSelf: "flex-start",
      })}
    >
      <AppIcon icon={RepeatIcon} size={13} color="#00bbff" />
      <Text style={{ color: "#00bbff", fontSize: 12, fontWeight: "600" }}>
        Retry
      </Text>
    </Pressable>
  );
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
          paddingVertical: spacing.md,
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

/** The received (AI) message text/OpenUI parts. */
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
  showToolProgress: boolean;
  showThinkingCard: boolean;
  showLoadingState: boolean;
  isLoading: boolean;
  isLastMessage: boolean;
  loadingMessage: string;
  progressToolName: string | null;
  progressMessage: string | null;
}

/** Main content area of an AI message — mutually exclusive render states. */
function AIMainContent({
  message,
  messageParts,
  isGeneratingImage,
  showToolProgress,
  showThinkingCard,
  showLoadingState,
  isLoading,
  isLastMessage,
  loadingMessage,
  progressToolName,
  progressMessage,
}: AIMainContentProps) {
  const { spacing } = useResponsive();
  const loadingText =
    loadingMessage !== "Thinking..." ? loadingMessage : undefined;

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
  if (showToolProgress) {
    return (
      <View style={{ paddingHorizontal: spacing.md, width: "100%" }}>
        <ToolProgressCard
          toolName={progressToolName}
          progressMessage={progressMessage}
        />
      </View>
    );
  }
  if (showThinkingCard) {
    return (
      <View style={{ paddingHorizontal: spacing.md, width: "100%" }}>
        <ThinkingCard message={loadingText} />
      </View>
    );
  }
  if (showLoadingState) {
    return <LoadingIndicator progress={loadingText} />;
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
  progressToolName,
  progressMessage,
  onFollowUpAction,
  onRetry,
}: ChatMessageLayoutProps & {
  parsedContent: ReturnType<typeof parseThinkingFromText>;
  messageParts: MessagePart[];
  isLoading: boolean;
  isLastMessage: boolean;
  loadingMessage: string;
  progressToolName: string | null;
  progressMessage: string | null;
  onFollowUpAction?: (action: string) => void;
  /** Re-run the failed turn (only meaningful when message.error is set). */
  onRetry?: () => void;
}) {
  const { spacing } = useResponsive();

  const hasContent = messageParts.length > 0;
  const showLoadingState = isLoading && !hasContent;
  const showToolProgress = showLoadingState && progressMessage !== null;
  const showThinkingCard = showLoadingState && !showToolProgress;
  const isGeneratingImage = message.imageData != null && !message.imageData.url;

  const rawText = message.text ?? "";
  const linkPreviewUrls = extractUrls(rawText);
  const { data: linkPreviewData } = useLinkPreview(
    !isLoading && rawText.length > 0 ? rawText : "",
  );

  const hasAnyContent =
    hasContent ||
    isGeneratingImage ||
    showToolProgress ||
    showThinkingCard ||
    showLoadingState ||
    !!parsedContent.thinking ||
    !!message.toolData?.length ||
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
          paddingVertical: spacing.sm,
          alignItems: "flex-start",
          width: "100%",
        }}
      >
        {/* Tool data cards — rendered inline before message text, matches
            web's chat_bubble_container flow (flex column, gap from cards).
            alignSelf: stretch so the wrapper fills the parent column —
            ToolCallsSection's expanded Input/Output panels need to span the
            full chat width, not collapse to icon+title content size. */}
        {message.toolData?.length ? (
          <View style={{ paddingHorizontal: spacing.md, alignSelf: "stretch" }}>
            <ToolDataRenderer toolData={message.toolData} />
          </View>
        ) : null}

        {/* Thinking / reasoning bubble (collapsible) */}
        {parsedContent.thinking ? (
          <View
            style={{ paddingHorizontal: spacing.md, marginBottom: spacing.xs }}
          >
            <ThinkingBubble thinkingContent={parsedContent.thinking} />
          </View>
        ) : null}

        {/* Main message content — full width, no avatar (mobile space constraint) */}
        <AIMainContent
          message={message}
          messageParts={messageParts}
          isGeneratingImage={isGeneratingImage}
          showToolProgress={showToolProgress}
          showThinkingCard={showThinkingCard}
          showLoadingState={showLoadingState}
          isLoading={isLoading}
          isLastMessage={isLastMessage}
          loadingMessage={loadingMessage}
          progressToolName={progressToolName}
          progressMessage={progressMessage}
        />

        {/* Link preview – shown below message content for AI messages */}
        {!isLoading && linkPreviewUrls.length > 0 && linkPreviewData?.length ? (
          <View
            style={{ paddingHorizontal: spacing.md, marginTop: spacing.xs }}
          >
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
          <MemoryIndicator memoryData={message.memoryData as MemoryDataShape} />
        ) : null}

        {/* Follow-up action chips */}
        {message.followUpActions?.length ? (
          <FollowUpActions
            actions={message.followUpActions}
            onActionPress={onFollowUpAction}
          />
        ) : null}

        {/* Errored turn: keep the streamed text above and mark the failure */}
        {message.error && !isLoading ? (
          <FailedResponse
            error={message.error}
            hasPartialText={hasContent}
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
  progressToolName = null,
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
      progressToolName={progressToolName}
      progressMessage={progressMessage}
      onFollowUpAction={onFollowUpAction}
      onRetry={onRetry}
    />
  );
}
