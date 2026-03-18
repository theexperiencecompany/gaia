import { getRelevantThinkingMessage } from "@gaia/shared/utils";
import type { FlashListRef } from "@shopify/flash-list";
import { FlashList } from "@shopify/flash-list";
import { useRouter } from "expo-router";
import type React from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Animated,
  Keyboard,
  KeyboardAvoidingView,
  LayoutAnimation,
  Platform,
  Pressable,
  RefreshControl,
  UIManager,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { useResponsive } from "@/lib/responsive";
import type { Message } from "../../api/chat-api";
import {
  branchConversation,
  deleteMessage,
  pinMessage,
} from "../../api/chat-api";
import { useChat } from "../../hooks/use-chat";
import { useChatContext } from "../../hooks/use-chat-context";
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

function MessageSkeleton() {
  const { spacing, moderateScale } = useResponsive();
  const opacity = useRef(new Animated.Value(0.3)).current;

  useEffect(() => {
    Animated.loop(
      Animated.sequence([
        Animated.timing(opacity, {
          toValue: 0.7,
          duration: 700,
          useNativeDriver: true,
        }),
        Animated.timing(opacity, {
          toValue: 0.3,
          duration: 700,
          useNativeDriver: true,
        }),
      ]),
    ).start();
  }, [opacity]);

  const bar = (width: number | `${number}%`, mt = 0) => (
    <Animated.View
      style={{
        height: moderateScale(12, 0.5),
        width,
        borderRadius: moderateScale(6, 0.5),
        backgroundColor: "rgba(255,255,255,0.12)",
        marginTop: mt,
        opacity,
      }}
    />
  );

  return (
    <View
      style={{ paddingHorizontal: spacing.md, paddingVertical: spacing.sm }}
    >
      <View style={{ maxWidth: "80%", marginBottom: spacing.md }}>
        {bar("90%")}
        {bar("75%", spacing.xs)}
        {bar("60%", spacing.xs)}
      </View>
      <View
        style={{
          maxWidth: "60%",
          alignSelf: "flex-end",
          marginBottom: spacing.md,
        }}
      >
        {bar("100%")}
        {bar("80%", spacing.xs)}
      </View>
      <View style={{ maxWidth: "85%" }}>
        {bar("85%")}
        {bar("70%", spacing.xs)}
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

  for (const message of messages) {
    const msgDate = new Date(message.timestamp);
    const dateKey = getDateKey(msgDate);

    if (dateKey !== lastDateKey) {
      items.push({
        type: "date-separator",
        date: message.timestamp.toISOString(),
        id: `date-${dateKey}`,
      });
      lastDateKey = dateKey;
    }

    items.push({ type: "message", data: message });
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
      () => {
        LayoutAnimation.configureNext(LayoutAnimation.Presets.easeInEaseOut);
        setTimeout(() => scrollToBottom(), 50);
      },
    );

    const keyboardWillHide = Keyboard.addListener(
      Platform.OS === "ios" ? "keyboardWillHide" : "keyboardDidHide",
      () => {
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

  const handleActionDelete = useCallback(
    async (messageId: string, conversationId: string) => {
      await deleteMessage(conversationId, messageId);
      await refetch();
    },
    [refetch],
  );

  const handleActionPin = useCallback(
    async (messageId: string, conversationId: string) => {
      await pinMessage(conversationId, messageId);
    },
    [],
  );

  const handleActionRetry = useCallback(
    (messageId: string, _conversationId: string) => {
      const msg = messages.find((m) => m.id === messageId);
      if (msg) {
        void sendMessage(msg.text, {
          replyToMessage: null,
          selectedWorkflow: null,
          selectedTool: null,
          toolCategory: null,
          attachments: [],
        });
      }
    },
    [messages, sendMessage],
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

  const handleActionRegenerate = useCallback(
    (messageId: string, _conversationId: string) => {
      const msgIndex = messages.findIndex((m) => m.id === messageId);
      if (msgIndex === -1) return;
      for (let i = msgIndex - 1; i >= 0; i--) {
        const candidate = messages[i];
        if (candidate.isUser) {
          void sendMessage(candidate.text, {
            replyToMessage: null,
            selectedWorkflow: null,
            selectedTool: null,
            toolCategory: null,
            attachments: [],
          });
          return;
        }
      }
    },
    [messages, sendMessage],
  );

  const handleActionBranch = useCallback(
    async (messageId: string, conversationId: string) => {
      const newConvId = await branchConversation(conversationId, messageId);
      if (newConvId) {
        router.push(`/(app)/c/${newConvId}`);
      }
    },
    [router],
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
          "Available commands: /new, /clear, /help, /model, /workflows, /integrations, /notifications, /settings",
        );
        return true;
      }

      if (command === "integrations") {
        router.push("/(app)/(tabs)/integrations");
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

      // /model is handled by the composer's model picker directly
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
          isLoading={showLoading}
          loadingMessage={showLoading ? displayMessage : undefined}
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

  return (
    <KeyboardAvoidingView
      style={{ flex: 1 }}
      behavior={Platform.OS === "ios" ? "padding" : undefined}
      keyboardVerticalOffset={0}
    >
      <View style={{ flex: 1 }}>
        {showSkeleton ? (
          <View style={{ flex: 1 }}>
            <MessageSkeleton />
          </View>
        ) : showEmptyState ? (
          <Pressable style={{ flex: 1 }} onPress={Keyboard.dismiss}>
            <EmptyChatState onSuggestionPress={handleFollowUpAction} />
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
              ]}
              contentContainerStyle={{
                paddingTop: spacing.md,
                paddingBottom: spacing.md,
              }}
              showsVerticalScrollIndicator
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
            paddingTop: spacing.sm,
            paddingBottom: insets.bottom + spacing.xs,
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
        onDelete={(messageId, conversationId) => {
          void handleActionDelete(messageId, conversationId);
        }}
        onPin={(messageId, conversationId) => {
          void handleActionPin(messageId, conversationId);
        }}
        onRetry={handleActionRetry}
        onReply={handleActionReply}
        onRegenerate={handleActionRegenerate}
        onBranch={(messageId, conversationId) => {
          void handleActionBranch(messageId, conversationId);
        }}
      />
    </KeyboardAvoidingView>
  );
}
