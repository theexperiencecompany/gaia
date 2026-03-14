import {
  parseThinkingFromText,
  splitMessageByBreaks,
} from "@gaia/shared/utils";
import * as Haptics from "expo-haptics";
import { Avatar, PressableFeedback } from "heroui-native";
import { useCallback, useMemo, useRef } from "react";
import { ScrollView, View } from "react-native";
import { AppIcon, Brain02Icon } from "@/components/icons";
import { MessageBubble } from "@/components/ui/message-bubble";
import { Text } from "@/components/ui/text";
import { useAuth } from "@/features/auth/hooks/use-auth";
import { ThinkingCard } from "@/features/chat/components/streaming/ThinkingCard";
import { ToolProgressCard } from "@/features/chat/components/streaming/ToolProgressCard";
import { useResponsive } from "@/lib/responsive";
import { extractUrls, useLinkPreview } from "../../hooks/use-link-preview";
import { ToolDataRenderer } from "../../tool-data/renderers";
import type { Message } from "../../types";
import {
  MemoryBottomSheet,
  type MemoryBottomSheetRef,
} from "../memory/memory-bottom-sheet";
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
  const { spacing, fontSize, moderateScale } = useResponsive();

  if (!actions.length) return null;

  return (
    <ScrollView
      horizontal
      showsHorizontalScrollIndicator={false}
      style={{ marginTop: spacing.sm }}
      contentContainerStyle={{
        flexDirection: "row",
        gap: spacing.sm,
        paddingLeft: moderateScale(32, 0.5),
        paddingRight: spacing.md,
      }}
      keyboardShouldPersistTaps="handled"
    >
      {actions.map((action) => (
        <PressableFeedback
          key={action}
          onPress={() => {
            Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
            onActionPress?.(action);
          }}
          style={{
            borderRadius: moderateScale(20, 0.5),
            borderWidth: 1,
            borderColor: "rgba(255,255,255,0.15)",
            backgroundColor: "rgba(255,255,255,0.05)",
            paddingHorizontal: spacing.md,
            paddingVertical: spacing.xs + 2,
          }}
        >
          <Text style={{ fontSize: fontSize.xs, color: "#ffffff" }}>
            {action}
          </Text>
        </PressableFeedback>
      ))}
    </ScrollView>
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
        paddingLeft: moderateScale(32, 0.5),
        paddingRight: spacing.md,
      }}
    >
      <View
        style={{
          flexDirection: "row",
          alignItems: "center",
          alignSelf: "flex-start",
          gap: spacing.xs,
          backgroundColor: "rgba(99, 102, 241, 0.12)",
          borderRadius: moderateScale(12, 0.5),
          paddingHorizontal: spacing.sm + 2,
          paddingVertical: spacing.xs,
          borderWidth: 1,
          borderColor: "rgba(99, 102, 241, 0.2)",
        }}
      >
        <AppIcon
          icon={Brain02Icon}
          size={moderateScale(11, 0.5)}
          color="#818cf8"
        />
        <Text
          style={{
            fontSize: fontSize.xs - 1,
            color: "#818cf8",
            fontWeight: "500",
          }}
        >
          {label}
        </Text>
      </View>
    </View>
  );
}

// -- User avatar --------------------------------------------------------------

interface UserAvatarProps {
  name?: string;
  picture?: string;
  size: number;
}

function UserAvatar({ name, picture, size }: UserAvatarProps) {
  const initials = name
    ? name
        .split(" ")
        .map((n) => n[0])
        .join("")
        .slice(0, 2)
        .toUpperCase()
    : "U";

  return (
    <Avatar
      alt={name ?? "User"}
      size="sm"
      color="default"
      style={{ width: size, height: size }}
    >
      {picture ? <Avatar.Image source={{ uri: picture }} /> : null}
      <Avatar.Fallback>
        <Text
          style={{
            fontSize: size * 0.4,
            fontWeight: "600",
            color: "#ffffff",
          }}
        >
          {initials}
        </Text>
      </Avatar.Fallback>
    </Avatar>
  );
}

// -- ChatMessage --------------------------------------------------------------

interface ChatMessageProps {
  message: Message;
  onFollowUpAction?: (action: string) => void;
  onReply?: (message: Message) => void;
  onLongPress?: (config: MessageActionConfig) => void;
  isLoading?: boolean;
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
  loadingMessage = "Thinking...",
  progressToolName = null,
  progressMessage = null,
}: ChatMessageProps) {
  const isUser = message.isUser;
  const { spacing, width, moderateScale } = useResponsive();
  const { user } = useAuth();
  const memorySheetRef = useRef<MemoryBottomSheetRef>(null);

  const avatarSize = moderateScale(24, 0.5);

  // Strip <thinking> tags from raw text so they are never rendered in the bubble.
  const parsedContent = useMemo(
    () => parseThinkingFromText(message.text ?? ""),
    [message.text],
  );

  const messageParts = splitMessageByBreaks(parsedContent.cleanText).filter(
    Boolean,
  );

  const _hasContent = messageParts.length > 0;
  const showLoadingState = !isUser && isLoading && !_hasContent;
  const showToolProgress = showLoadingState && progressMessage !== null;
  const showThinkingCard = showLoadingState && !showToolProgress;

  // Determine if the image is still being generated (imageData present but url is empty)
  const isGeneratingImage =
    !isUser && message.imageData != null && !message.imageData.url;

  const rawText = message.text ?? "";
  const linkPreviewUrls = !isUser ? extractUrls(rawText) : [];
  const { data: linkPreviewData } = useLinkPreview(
    !isUser && !isLoading && rawText.length > 0 ? rawText : "",
  );

  // Message max width adapts to screen size (80% of screen width, min 280, max 400)
  const messageMaxWidth = Math.min(Math.max(width * 0.8, 280), 400);

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
      <PressableFeedback
        onLongPress={handleLongPress}
        delayLongPress={350}
        style={{
          flexDirection: "row",
          paddingVertical: spacing.sm,
          alignItems: "flex-end",
          justifyContent: "flex-end",
          paddingHorizontal: spacing.md,
          gap: spacing.sm,
        }}
      >
        <View
          style={{
            flexDirection: "column",
            gap: spacing.xs,
            maxWidth: messageMaxWidth,
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
                showAvatar={false}
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

        <UserAvatar
          name={user?.name}
          picture={user?.picture}
          size={avatarSize}
        />
      </PressableFeedback>
    );
  }

  // ---- AI message ----------------------------------------------------------
  return (
    <PressableFeedback
      onLongPress={handleLongPress}
      delayLongPress={350}
      style={{
        flexDirection: "column",
        paddingVertical: spacing.sm,
        alignItems: "flex-start",
      }}
    >
      <View
        style={{
          flexDirection: "column",
          gap: spacing.sm,
          paddingHorizontal: spacing.md,
          maxWidth: messageMaxWidth,
        }}
      >
        {/* Tool data cards */}
        {message.toolData?.length ? (
          <ToolDataRenderer toolData={message.toolData} />
        ) : null}

        {/* Thinking / reasoning bubble (collapsible) */}
        {parsedContent.thinking ? (
          <View style={{ paddingLeft: avatarSize + spacing.sm }}>
            <ThinkingBubble thinkingContent={parsedContent.thinking} />
          </View>
        ) : null}

        {/* Image data */}
        {message.imageData || isGeneratingImage ? (
          <ImageBubble
            imageData={message.imageData ?? { url: "", prompt: "" }}
            isGenerating={isGeneratingImage}
            caption={
              messageParts.length > 0 ? messageParts.join(" ") : undefined
            }
          />
        ) : showToolProgress ? (
          <ToolProgressCard
            toolName={progressToolName}
            progressMessage={progressMessage}
          />
        ) : showThinkingCard ? (
          <ThinkingCard />
        ) : showLoadingState ? (
          <LoadingIndicator
            progress={
              loadingMessage !== "Thinking..." ? loadingMessage : undefined
            }
          />
        ) : (
          messageParts.map((part, index) => (
            <MessageBubble
              key={`${message.id}-${index}`}
              message={part}
              variant="received"
              showAvatar={index === 0}
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
          ))
        )}

        {/* Link preview – shown below message content for AI messages */}
        {!isUser &&
        !isLoading &&
        linkPreviewUrls.length > 0 &&
        linkPreviewData?.length ? (
          <LinkPreviewCard
            url={linkPreviewData[0].url}
            title={linkPreviewData[0].title}
            description={linkPreviewData[0].description}
            imageUrl={linkPreviewData[0].imageUrl}
            favicon={linkPreviewData[0].favicon}
            domain={linkPreviewData[0].domain}
          />
        ) : null}
      </View>

      {/* Memory indicator pill – shown below the AI message when memory was updated */}
      {message.memoryData ? (
        <PressableFeedback
          onPress={() =>
            memorySheetRef.current?.open(message.memoryData as MemoryDataShape)
          }
        >
          <MemoryIndicator memoryData={message.memoryData as MemoryDataShape} />
        </PressableFeedback>
      ) : null}

      {/* Follow-up action chips */}
      {message.followUpActions?.length ? (
        <FollowUpActions
          actions={message.followUpActions}
          onActionPress={onFollowUpAction}
        />
      ) : null}

      <MemoryBottomSheet ref={memorySheetRef} />
    </PressableFeedback>
  );
}
