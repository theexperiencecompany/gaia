import { FlashList } from "@shopify/flash-list";
import { useRouter } from "expo-router";
import { useCallback, useEffect, useState } from "react";
import {
  Keyboard,
  KeyboardAvoidingView,
  LayoutAnimation,
  Platform,
  Pressable,
  ScrollView,
  UIManager,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { ChatInput } from "@/components/ui/chat-input";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import type { Message } from "../../api/chat-api";
import { useChat } from "../../hooks/use-chat";
import { useChatContext } from "../../hooks/use-chat-context";
import { getRelevantThinkingMessage } from "../../utils/playfulThinking";
import { ChatMessage } from "./chat-message";

function EmptyState() {
  return (
    <ScrollView
      contentContainerStyle={{
        flexGrow: 1,
        alignItems: "center",
        justifyContent: "center",
      }}
      keyboardShouldPersistTaps="handled"
    >
      <Text className="text-3xl font-semibold text-center">
        What can I help you with?
      </Text>
      <Text className="text-xs text-gray-200 mt-2 text-center">
        Start a conversation by typing a message below
      </Text>
    </ScrollView>
  );
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
    progress,
    flatListRef,
    sendMessage,
    scrollToBottom,
  } = useChat(activeChatId, { onNavigate });

  const { spacing, moderateScale } = useResponsive();
  const { setActiveChatId, clearActiveMessages } = useChatContext();
  const router = useRouter();
  const insets = useSafeAreaInsets();

  const [inputValue, setInputValue] = useState("");
  const [lastUserMessage, setLastUserMessage] = useState("");
  const [thinkingMessage, setThinkingMessage] = useState(() =>
    getRelevantThinkingMessage(""),
  );

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
    scrollToBottom();
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

  const handleFollowUpAction = useCallback((action: string) => {
    setInputValue(action);
  }, []);

  const handleSend = useCallback(
    (text: string) => {
      setLastUserMessage(text);
      void sendMessage(text);
      setInputValue("");
    },
    [sendMessage],
  );

  const handleCommand = useCallback(
    (command: string) => {
      if (command === "new") {
        clearActiveMessages();
        setActiveChatId(null);
        setInputValue("");
        setLastUserMessage("");
        router.replace("/(app)/index");
        return true;
      }

      if (command === "integrations") {
        router.push("/(app)/integrations");
        return true;
      }

      if (command === "workflows") {
        router.push("/(app)/workflows");
        return true;
      }

      if (command === "notifications") {
        router.push("/(app)/notifications");
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

  const renderMessage = useCallback(
    ({ item, index }: { item: Message; index: number }) => {
      const isLastMessage = index === messages.length - 1;
      const isEmptyAiMessage =
        !item.isUser && (!item.text || item.text.trim() === "");
      const showLoading = isLastMessage && isEmptyAiMessage && isTyping;

      return (
        <ChatMessage
          message={item}
          onFollowUpAction={handleFollowUpAction}
          isLoading={showLoading}
          loadingMessage={showLoading ? displayMessage : undefined}
        />
      );
    },
    [displayMessage, handleFollowUpAction, isTyping, messages.length],
  );

  const showEmptyState = messages.length === 0 && !isTyping && !activeChatId;

  return (
    <KeyboardAvoidingView
      style={{ flex: 1 }}
      behavior={Platform.OS === "ios" ? "height" : undefined}
      keyboardVerticalOffset={
        Platform.OS === "ios" ? insets.top + spacing.xl : 0
      }
    >
      <View style={{ flex: 1 }}>
        {showEmptyState ? (
          <Pressable style={{ flex: 1 }} onPress={Keyboard.dismiss}>
            <EmptyState />
          </Pressable>
        ) : (
          <FlashList
            ref={flatListRef}
            data={messages}
            renderItem={renderMessage}
            keyExtractor={(item) => item.id}
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
            onLoad={() => {
              if (messages.length > 0) {
                flatListRef.current?.scrollToEnd({ animated: false });
              }
            }}
          />
        )}

        <View
          style={{
            paddingHorizontal: spacing.sm,
            paddingTop: spacing.sm,
            paddingBottom: insets.bottom + spacing.md,
            backgroundColor: "#131416",
            borderTopLeftRadius: moderateScale(24, 0.5),
            borderTopRightRadius: moderateScale(24, 0.5),
            borderTopWidth: 1,
            borderTopColor: "rgba(255,255,255,0.08)",
          }}
        >
          <ChatInput
            onSend={handleSend}
            value={inputValue}
            onChangeText={setInputValue}
            onCommand={handleCommand}
          />
        </View>
      </View>
    </KeyboardAvoidingView>
  );
}
