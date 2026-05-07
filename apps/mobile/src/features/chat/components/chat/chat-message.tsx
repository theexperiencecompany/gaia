import {
  parseOpenUISegments,
  parseThinkingFromText,
  splitByBreaksPreservingFences,
} from "@gaia/shared/utils";
import * as Haptics from "expo-haptics";
import { PressableFeedback } from "heroui-native";
import { useCallback, useMemo } from "react";
import { Pressable, View } from "react-native";
import Animated, { FadeIn, FadeInDown } from "react-native-reanimated";
import { AppIcon, Brain02Icon } from "@/components/icons";
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
  if (!actions.length) return null;

  return (
    <View
      className="flex-row flex-wrap gap-2 mt-2"
      style={{ paddingLeft: 46, paddingRight: 16 }}
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

// -- ChatMessage --------------------------------------------------------------

interface ChatMessageProps {
  message: Message;
  onFollowUpAction?: (action: string) => void;
  onReply?: (message: Message) => void;
  onLongPress?: (config: MessageActionConfig) => void;
  isLoading?: boolean;
  isLastMessage?: boolean;
  loadingMessage?: string;
  progressToolName?: string | null;
  progressMessage?: string | null;
}

export function ChatMessage({
  message,
  onFollowUpAction,
  onReply,
  onLongPress,
  isLoading = false,
  isLastMessage = false,
  loadingMessage = "Thinking...",
  progressToolName = null,
  progressMessage = null,
}: ChatMessageProps) {
  const isUser = message.isUser;
  const { spacing } = useResponsive();

  // Strip <thinking> tags from raw text so they are never rendered in the bubble.
  const parsedContent = useMemo(
    () => parseThinkingFromText(message.text ?? ""),
    [message.text],
  );

  const messageParts = splitByBreaksPreservingFences(
    parsedContent.cleanText,
  ).filter(Boolean);

  const _hasContent = messageParts.length > 0;
  const showLoadingState = !isUser && isLoading && !_hasContent;
  const showToolProgress = showLoadingState && progressMessage !== null;
  const showThinkingCard = showLoadingState && !showToolProgress;

  const isGeneratingImage =
    !isUser && message.imageData != null && !message.imageData.url;

  const rawText = message.text ?? "";
  const linkPreviewUrls = !isUser ? extractUrls(rawText) : [];
  const { data: linkPreviewData } = useLinkPreview(
    !isUser && !isLoading && rawText.length > 0 ? rawText : "",
  );

  const handleLongPress = useCallback(() => {
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

  // ---- User message --------------------------------------------------------
  if (isUser) {
    return (
      <Animated.View entering={FadeIn.duration(200)}>
        <PressableFeedback
          onLongPress={handleLongPress}
          onPressIn={() =>
            Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light)
          }
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
            style={{
              flexDirection: "column",
              gap: spacing.xs,
              maxWidth: "80%",
            }}
          >
            {message.replyToMessage && (
              <MessageReplyQuote
                replyToMessage={message.replyToMessage}
                isUserMessage={true}
              />
            )}
            {messageParts.map((part, index) => {
              const { isEmojiOnly, count } = getEmojiInfo(part);
              if (isEmojiOnly && messageParts.length === 1) {
                const emojiSize =
                  count === 1 ? 52 : count === 2 ? 40 : count === 3 ? 32 : null;
                if (emojiSize) {
                  return (
                    <Text
                      key={`${message.id}-${index}`}
                      style={{
                        fontSize: emojiSize,
                        lineHeight: emojiSize + 8,
                      }}
                    >
                      {part}
                    </Text>
                  );
                }
              }
              return (
                <MessageBubble
                  key={`${message.id}-${index}`}
                  message={part}
                  variant="sent"
                  grouped={
                    messageParts.length === 1
                      ? "none"
                      : index === 0
                        ? "first"
                        : index === messageParts.length - 1
                          ? "last"
                          : "middle"
                  }
                />
              );
            })}
          </View>
        </PressableFeedback>
      </Animated.View>
    );
  }

  // ---- AI message ----------------------------------------------------------
  // Don't render an empty wrapper — only render if there's actual content to show
  const hasAnyContent =
    messageParts.length > 0 ||
    isGeneratingImage ||
    showToolProgress ||
    showThinkingCard ||
    showLoadingState ||
    !!parsedContent.thinking ||
    !!message.toolData?.length ||
    !!message.memoryData ||
    !!message.followUpActions?.length;

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
        {message.imageData || isGeneratingImage ? (
          <View style={{ paddingHorizontal: spacing.md, width: "100%" }}>
            <ImageBubble
              imageData={message.imageData ?? { url: "", prompt: "" }}
              isGenerating={isGeneratingImage}
              caption={
                messageParts.length > 0 ? messageParts.join(" ") : undefined
              }
            />
          </View>
        ) : showToolProgress ? (
          <View style={{ paddingHorizontal: spacing.md, width: "100%" }}>
            <ToolProgressCard
              toolName={progressToolName}
              progressMessage={progressMessage}
            />
          </View>
        ) : showThinkingCard ? (
          <View style={{ paddingHorizontal: spacing.md, width: "100%" }}>
            <ThinkingCard
              message={
                loadingMessage !== "Thinking..." ? loadingMessage : undefined
              }
            />
          </View>
        ) : showLoadingState ? (
          <LoadingIndicator
            progress={
              loadingMessage !== "Thinking..." ? loadingMessage : undefined
            }
          />
        ) : messageParts.length > 0 ? (
          messageParts.map((part, partIndex) => {
            const segments = parseOpenUISegments(part, !!isLoading);
            const grouped =
              messageParts.length === 1
                ? "none"
                : partIndex === 0
                  ? "first"
                  : partIndex === messageParts.length - 1
                    ? "last"
                    : "middle";

            const totalSegments = segments.length;
            return segments.map((segment, segIndex) => {
              const key = `${message.id}-${partIndex}-${segIndex}`;
              const isLastSegmentOfLastPart =
                partIndex === messageParts.length - 1 &&
                segIndex === totalSegments - 1;
              const showCursor =
                isLoading && isLastMessage && isLastSegmentOfLastPart;

              if (segment.type === "openui") {
                return (
                  <View
                    key={key}
                    style={{
                      paddingHorizontal: spacing.md,
                      width: "100%",
                    }}
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
          })
        ) : null}

        {/* Link preview – shown below message content for AI messages */}
        {!isUser &&
        !isLoading &&
        linkPreviewUrls.length > 0 &&
        linkPreviewData?.length ? (
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
      </PressableFeedback>
    </Animated.View>
  );
}
