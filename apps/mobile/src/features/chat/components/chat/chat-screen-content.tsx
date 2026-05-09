import { getRelevantThinkingMessage } from "@gaia/shared/utils";
import type { FlashListRef } from "@shopify/flash-list";
import { FlashList } from "@shopify/flash-list";
import { useRouter } from "expo-router";
import type React from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Keyboard,
  KeyboardAvoidingView,
  LayoutAnimation,
  Platform,
  Pressable,
  RefreshControl,
  UIManager,
  View,
} from "react-native";
import Reanimated, {
  useAnimatedStyle,
  useSharedValue,
  withDelay,
  withRepeat,
  withSequence,
  withTiming,
} from "react-native-reanimated";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { useResponsive } from "@/lib/responsive";
import type { Message } from "../../api/chat-api";
import { pinMessage } from "../../api/chat-api";
import { useChat } from "../../hooks/use-chat";
import { useChatContext } from "../../hooks/use-chat-context";
import {
  useComposerStore,
  usePendingPrompt,
} from "../../stores/composer-store";
import type { ReplyToMessageData } from "../../types";
import type { AttachmentFile } from "../composer/attachment-preview";
import { Composer } from "../composer/composer";
import { ChatMessage } from "./chat-message";
import { DateSeparator } from "./date-separator";
import { EmptyChatState } from "./empty-chat-state";
import type {
  MessageActionConfig,
  MessageActionSheetRef,
} from "./message-action-sheet";
import { MessageActionSheet } from "./message-action-sheet";
import { ScrollToBottomButton } from "./scroll-to-bottom";

// ---------------------------------------------------------------------------
// Loading skeleton shown while fetching an existing conversation
// ---------------------------------------------------------------------------

function SkeletonBar({
  width,
  mt,
  delayMs,
  barHeight,
  borderRadius,
}: {
  width: number | `${number}%`;
  mt: number;
  delayMs: number;
  barHeight: number;
  borderRadius: number;
}) {
  const opacity = useSharedValue(0.3);

  useEffect(() => {
    opacity.value = withDelay(
      delayMs,
      withRepeat(
        withSequence(
          withTiming(0.7, { duration: 700 }),
          withTiming(0.3, { duration: 700 }),
        ),
        -1,
      ),
    );
  }, [opacity, delayMs]);

  const animatedStyle = useAnimatedStyle(() => ({ opacity: opacity.value }));

  return (
    <Reanimated.View
      style={[
        {
          height: barHeight,
          width,
          borderRadius,
          backgroundColor: "rgba(255,255,255,0.12)",
          marginTop: mt,
        },
        animatedStyle,
      ]}
    />
  );
}

function MessageSkeleton() {
  const { spacing, moderateScale } = useResponsive();
  const barH = moderateScale(12, 0.5);
  const br = moderateScale(6, 0.5);

  const bar = (width: number | `${number}%`, mt: number, delayMs: number) => (
    <SkeletonBar
      width={width}
      mt={mt}
      delayMs={delayMs}
      barHeight={barH}
      borderRadius={br}
    />
  );

  return (
    <View
      style={{ paddingHorizontal: spacing.md, paddingVertical: spacing.sm }}
    >
      <View style={{ maxWidth: "80%", marginBottom: spacing.md }}>
        {bar("90%", 0, 0)}
        {bar("75%", spacing.xs, 100)}
        {bar("60%", spacing.xs, 200)}
      </View>
      <View
        style={{
          maxWidth: "60%",
          alignSelf: "flex-end",
          marginBottom: spacing.md,
        }}
      >
        {bar("100%", 0, 300)}
        {bar("80%", spacing.xs, 400)}
      </View>
      <View style={{ maxWidth: "85%" }}>
        {bar("85%", 0, 500)}
        {bar("70%", spacing.xs, 600)}
      </View>
    </View>
  );
}

// ---------------------------------------------------------------------------

type ListItem =
  | { type: "message"; data: Message }
  | { type: "date-separator"; date: string; id: string };

function getDateKey(date: Date): string {
  return `${date.getFullYear()}-${date.getMonth()}-${date.getDate()}`;
}

function buildListItems(messages: Message[]): ListItem[] {
  const items: ListItem[] = [];
  let lastDateKey: string | null = null;
  const todayKey = getDateKey(new Date());
  const seenDateKeys = new Set<string>();

  for (const message of messages) {
    const msgDate = new Date(message.timestamp);
    const dateKey = getDateKey(msgDate);

    if (dateKey !== lastDateKey) {
      items.push({
        type: "date-separator",
        date: message.timestamp.toISOString(),
        id: `date-${dateKey}`,
      });
      seenDateKeys.add(dateKey);
      lastDateKey = dateKey;
    }

    items.push({ type: "message", data: message });
  }

  // Hide "Today" separator when it's the only date group — adds no value
  if (seenDateKeys.size === 1 && seenDateKeys.has(todayKey)) {
    return items.filter((i) => i.type !== "date-separator");
  }

  return items;
}

interface ChatScreenContentProps {
  activeChatId: string | null;
  onNavigate?: (conversationId: string) => void;
}

export function ChatScreenContent({
  activeChatId,
  onNavigate,
}: ChatScreenContentProps) {
  const {
    messages,
    isTyping,
    isLoading,
    progress,
    progressToolName,
    flatListRef,
    sendMessage,
    cancelStream,
    scrollToBottom,
    refetch,
  } = useChat(activeChatId, { onNavigate });

  const { spacing } = useResponsive();
  const { setActiveChatId, clearActiveMessages } = useChatContext();
  const router = useRouter();
  const insets = useSafeAreaInsets();

  const [inputValue, setInputValue] = useState("");
  const pendingPrompt = usePendingPrompt();
  const consumePendingPrompt = useComposerStore(
    (state) => state.consumePendingPrompt,
  );
  useEffect(() => {
    if (pendingPrompt) {
      setInputValue(pendingPrompt);
      consumePendingPrompt();
    }
  }, [pendingPrompt, consumePendingPrompt]);
  const [lastUserMessage, setLastUserMessage] = useState("");
  const [thinkingMessage, setThinkingMessage] = useState(() =>
    getRelevantThinkingMessage(""),
  );

  const [selectedTool, setSelectedTool] = useState<{
    name: string;
    category: string;
  } | null>(null);
  const [selectedWorkflow, setSelectedWorkflow] = useState<{
    id: string;
    title: string;
  } | null>(null);

  const [replyingTo, setReplyingTo] = useState<ReplyToMessageData | null>(null);

  const actionSheetRef = useRef<MessageActionSheetRef>(null);
  const [actionConfig, setActionConfig] = useState<MessageActionConfig | null>(
    null,
  );

  const [isRefreshing, setIsRefreshing] = useState(false);
  const [showScrollToBottom, setShowScrollToBottom] = useState(false);
  const isAtBottomRef = useRef(true);
  const [androidKeyboardHeight, setAndroidKeyboardHeight] = useState(0);

  // Clear input state when switching conversations
  useEffect(() => {
    setInputValue("");
    setReplyingTo(null);
    setSelectedTool(null);
    setSelectedWorkflow(null);
  }, [activeChatId]);

  useEffect(() => {
    if (isTyping && !progress) {
      setThinkingMessage(getRelevantThinkingMessage(lastUserMessage));
      const interval = setInterval(
        () => {
          setThinkingMessage(getRelevantThinkingMessage(lastUserMessage));
        },
        2000 + Math.random() * 1000,
      );
      return () => clearInterval(interval);
    }
  }, [isTyping, progress, lastUserMessage]);

  const displayMessage = progress || thinkingMessage;

  useEffect(() => {
    if (isAtBottomRef.current) {
      scrollToBottom();
    }
  }, [messages.length, scrollToBottom]);

  useEffect(() => {
    if (
      Platform.OS === "android" &&
      UIManager.setLayoutAnimationEnabledExperimental
    ) {
      UIManager.setLayoutAnimationEnabledExperimental(true);
    }

    const keyboardWillShow = Keyboard.addListener(
      Platform.OS === "ios" ? "keyboardWillShow" : "keyboardDidShow",
      (e) => {
        if (Platform.OS === "android") {
          setAndroidKeyboardHeight(e.endCoordinates.height);
        }
        LayoutAnimation.configureNext(LayoutAnimation.Presets.easeInEaseOut);
        setTimeout(() => scrollToBottom(), 50);
      },
    );

    const keyboardWillHide = Keyboard.addListener(
      Platform.OS === "ios" ? "keyboardWillHide" : "keyboardDidHide",
      () => {
        if (Platform.OS === "android") {
          setAndroidKeyboardHeight(0);
        }
        LayoutAnimation.configureNext(LayoutAnimation.Presets.easeInEaseOut);
      },
    );

    return () => {
      keyboardWillShow.remove();
      keyboardWillHide.remove();
    };
  }, [scrollToBottom]);

  // Populate the input rather than immediately sending, matching web behaviour
  const handleFollowUpAction = useCallback((action: string) => {
    setInputValue(action);
  }, []);

  const handleReply = useCallback((message: Message) => {
    setReplyingTo({
      id: message.id,
      content:
        message.text.length > 150
          ? `${message.text.slice(0, 150)}...`
          : message.text,
      role: message.isUser ? "user" : "assistant",
    });
  }, []);

  const handleLongPressMessage = useCallback(
    (config: MessageActionConfig) => {
      const resolved: MessageActionConfig = {
        ...config,
        conversationId: config.conversationId || activeChatId || "",
      };
      setActionConfig(resolved);
      actionSheetRef.current?.open();
    },
    [activeChatId],
  );

  const handleActionPin = useCallback(
    async (messageId: string, conversationId: string) => {
      await pinMessage(conversationId, messageId);
    },
    [],
  );

  const handleActionReply = useCallback(
    (messageId: string, _conversationId: string) => {
      const msg = messages.find((m) => m.id === messageId);
      if (msg) {
        handleReply(msg);
      }
    },
    [messages, handleReply],
  );

  const handleSend = useCallback(
    (text: string, attachments: AttachmentFile[]) => {
      setLastUserMessage(text);
      void sendMessage(text, {
        replyToMessage: replyingTo,
        selectedWorkflow: selectedWorkflow
          ? { id: selectedWorkflow.id, name: selectedWorkflow.title }
          : null,
        selectedTool: selectedTool?.name ?? null,
        toolCategory: selectedTool?.category ?? null,
        attachments,
      });
      setInputValue("");
      setSelectedTool(null);
      setSelectedWorkflow(null);
      setReplyingTo(null);
    },
    [sendMessage, replyingTo, selectedWorkflow, selectedTool],
  );

  const handleToolSelected = useCallback(
    (toolName: string, toolCategory: string) => {
      setSelectedTool({ name: toolName, category: toolCategory });
      setSelectedWorkflow(null);
    },
    [],
  );

  const handleWorkflowSelected = useCallback(
    (workflow: { id: string; title: string }) => {
      setSelectedWorkflow(workflow);
      setSelectedTool(null);
    },
    [],
  );

  const handleCommand = useCallback(
    (command: string) => {
      if (command === "new") {
        clearActiveMessages();
        setActiveChatId(null);
        setInputValue("");
        setLastUserMessage("");
        router.replace("/");
        return true;
      }

      if (command === "clear") {
        clearActiveMessages();
        setInputValue("");
        setLastUserMessage("");
        setReplyingTo(null);
        setSelectedTool(null);
        setSelectedWorkflow(null);
        return true;
      }

      if (command === "help") {
        setInputValue(
          "Available commands: /new, /clear, /help, /workflows, /integrations, /notifications, /settings",
        );
        return true;
      }

      if (command === "integrations") {
        router.push("/(app)/integrations");
        return true;
      }

      if (command === "workflows") {
        router.push("/(app)/(tabs)/workflows");
        return true;
      }

      if (command === "notifications") {
        router.push("/(app)/(tabs)/notifications");
        return true;
      }

      if (command === "settings") {
        router.push("/(app)/settings");
        return true;
      }

      return false;
    },
    [clearActiveMessages, router, setActiveChatId],
  );

  const handleRefresh = useCallback(async () => {
    setIsRefreshing(true);
    await refetch();
    setIsRefreshing(false);
  }, [refetch]);

  const handleScrollToBottom = useCallback(() => {
    isAtBottomRef.current = true;
    setShowScrollToBottom(false);
    scrollToBottom();
  }, [scrollToBottom]);

  const handleScroll = useCallback(
    (event: {
      nativeEvent: {
        contentOffset: { y: number };
        contentSize: { height: number };
        layoutMeasurement: { height: number };
      };
    }) => {
      const { contentOffset, contentSize, layoutMeasurement } =
        event.nativeEvent;
      const distanceFromBottom =
        contentSize.height - contentOffset.y - layoutMeasurement.height;
      const atBottom = distanceFromBottom < 80;
      isAtBottomRef.current = atBottom;
      setShowScrollToBottom(!atBottom);
    },
    [],
  );

  const listItems = useMemo(() => buildListItems(messages), [messages]);

  const renderItem = useCallback(
    ({ item }: { item: ListItem }) => {
      if (item.type === "date-separator") {
        return <DateSeparator date={item.date} />;
      }

      const message = item.data;
      const msgIndex = messages.findIndex((m) => m.id === message.id);
      const isLastMessage = msgIndex === messages.length - 1;
      const isEmptyAiMessage =
        !message.isUser && (!message.text || message.text.trim() === "");
      const showLoading = isLastMessage && isEmptyAiMessage && isTyping;

      return (
        <ChatMessage
          message={message}
          onFollowUpAction={handleFollowUpAction}
          onReply={handleReply}
          onLongPress={handleLongPressMessage}
          isLoading={isLastMessage && isTyping}
          isLastMessage={isLastMessage}
          loadingMessage={showLoading ? displayMessage : undefined}
          progressToolName={showLoading ? progressToolName : null}
          progressMessage={showLoading ? progress : null}
        />
      );
    },
    [
      displayMessage,
      handleFollowUpAction,
      handleLongPressMessage,
      handleReply,
      isTyping,
      messages,
      progress,
      progressToolName,
    ],
  );

  const keyExtractor = useCallback((item: ListItem) => {
    if (item.type === "date-separator") return item.id;
    return item.data.id;
  }, []);

  const showEmptyState = messages.length === 0 && !isTyping && !activeChatId;
  // Only show skeleton when opening an existing chat that hasn't loaded yet
  const showSkeleton =
    isLoading && !isTyping && !!activeChatId && messages.length === 0;

  // Breathing space between top of soft keyboard and bottom of composer pill.
  const KEYBOARD_GAP = 10;

  return (
    <KeyboardAvoidingView
      style={{ flex: 1 }}
      behavior={Platform.OS === "ios" ? "padding" : undefined}
      keyboardVerticalOffset={Platform.OS === "ios" ? 56 - KEYBOARD_GAP : 0}
    >
      <View
        style={{
          flex: 1,
          paddingBottom:
            Platform.OS === "android" && androidKeyboardHeight > 0
              ? androidKeyboardHeight + KEYBOARD_GAP
              : 0,
        }}
      >
        {showSkeleton ? (
          <View style={{ flex: 1 }}>
            <MessageSkeleton />
          </View>
        ) : showEmptyState ? (
          <Pressable style={{ flex: 1 }} onPress={Keyboard.dismiss}>
            <EmptyChatState />
          </Pressable>
        ) : (
          <View style={{ flex: 1 }}>
            <FlashList
              ref={
                flatListRef as React.RefObject<FlashListRef<ListItem> | null>
              }
              data={listItems}
              renderItem={renderItem}
              keyExtractor={keyExtractor}
              extraData={[
                messages[messages.length - 1]?.text,
                isTyping,
                displayMessage,
                progress,
                progressToolName,
              ]}
              contentContainerStyle={{
                paddingTop: spacing.md,
                paddingBottom: spacing.md,
              }}
              showsVerticalScrollIndicator={false}
              keyboardShouldPersistTaps="handled"
              keyboardDismissMode="on-drag"
              onScroll={handleScroll}
              scrollEventThrottle={16}
              refreshControl={
                <RefreshControl
                  refreshing={isRefreshing}
                  onRefresh={handleRefresh}
                  tintColor="#00bbff"
                />
              }
              onLoad={() => {
                if (messages.length > 0) {
                  flatListRef.current?.scrollToEnd({ animated: false });
                }
              }}
            />
            <ScrollToBottomButton
              visible={showScrollToBottom}
              onPress={handleScrollToBottom}
            />
          </View>
        )}

        <View
          style={{
            paddingHorizontal: spacing.sm,
            paddingTop: spacing.xs,
            paddingBottom: insets.bottom,
          }}
        >
          <Composer
            onSend={handleSend}
            value={inputValue}
            onChangeText={setInputValue}
            onCommand={handleCommand}
            isStreaming={isTyping}
            onCancel={cancelStream}
            selectedTool={selectedTool}
            onRemoveTool={() => setSelectedTool(null)}
            selectedWorkflow={selectedWorkflow}
            onRemoveWorkflow={() => setSelectedWorkflow(null)}
            onToolSelected={handleToolSelected}
            onWorkflowSelected={handleWorkflowSelected}
            replyTo={replyingTo}
            onRemoveReply={() => setReplyingTo(null)}
          />
        </View>
      </View>

      <MessageActionSheet
        ref={actionSheetRef}
        config={actionConfig}
        onPin={(messageId, conversationId) => {
          void handleActionPin(messageId, conversationId);
        }}
        onReply={handleActionReply}
      />
    </KeyboardAvoidingView>
  );
}
