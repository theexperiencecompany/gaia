import { useCallback, useEffect, useState } from "react";
import { FlashList } from "@shopify/flash-list";
import { Image, Keyboard, Pressable, View } from "react-native";
import { Text } from "@/components/ui/text";
import { LinearGradient } from "expo-linear-gradient";
import Animated, {
  Easing,
  runOnJS,
  useAnimatedKeyboard,
  useAnimatedReaction,
  useAnimatedStyle,
  useSharedValue,
  withTiming,
} from "react-native-reanimated";
import { ChatInput } from "@/components/ui/chat-input";
import {
  ChatLayout,
  ChatMessage,
  type Message,
  useChat,
  useChatContext,
} from "@/features/chat";
import { getRelevantThinkingMessage } from "@/features/chat/utils/playfulThinking";

function EmptyState() {
  return (
    <View className="flex-1 items-center justify-center px-6">
      <Text variant={"h2"}>What can I help you with?</Text>
      <Text className="text-xs">
        Start a conversation by typing a message below
      </Text>
    </View>
  );
}

function ChatContent({
  activeChatId,
  onFollowUpAction,
}: {
  activeChatId: string | null;
  onFollowUpAction?: (action: string) => void;
}) {
  const {
    messages,
    isTyping,
    progress,
    flatListRef,
    sendMessage,
    scrollToBottom,
  } = useChat(activeChatId);

  const [inputValue, setInputValue] = useState("");
  const [lastUserMessage, setLastUserMessage] = useState("");
  const [thinkingMessage, setThinkingMessage] = useState(() =>
    getRelevantThinkingMessage("")
  );

  const keyboard = useAnimatedKeyboard();

  const animatedInputStyle = useAnimatedStyle(() => ({
    bottom: keyboard.height.value,
  }));

  useEffect(() => {
    if (isTyping && !progress) {
      setThinkingMessage(getRelevantThinkingMessage(lastUserMessage));
      const interval = setInterval(
        () => {
          setThinkingMessage(getRelevantThinkingMessage(lastUserMessage));
        },
        2000 + Math.random() * 1000
      );
      return () => clearInterval(interval);
    }
  }, [isTyping, progress, lastUserMessage]);

  const displayMessage = progress || thinkingMessage;

  useEffect(() => {
    scrollToBottom();
  }, [messages.length, scrollToBottom]);

  useAnimatedReaction(
    () => keyboard.height.value,
    (currentHeight, previousHeight) => {
      if (
        currentHeight > 0 &&
        (previousHeight === null || currentHeight > previousHeight)
      ) {
        runOnJS(scrollToBottom)();
      }
    }
  );

  const handleFollowUpAction = useCallback(
    (action: string) => {
      setInputValue(action);
      onFollowUpAction?.(action);
    },
    [onFollowUpAction]
  );

  const handleSend = useCallback(
    (text: string) => {
      setLastUserMessage(text);
      sendMessage(text);
      setInputValue("");
    },
    [sendMessage]
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
    [handleFollowUpAction, messages.length, isTyping, displayMessage]
  );

  const showEmptyState = messages.length === 0 && !isTyping && !activeChatId;

  return (
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
            paddingTop: 16,
            paddingBottom: 90,
          }}
          showsVerticalScrollIndicator={true}
          keyboardShouldPersistTaps="handled"
          keyboardDismissMode="on-drag"
          onLoad={() => {
            if (messages.length > 0) {
              flatListRef.current?.scrollToEnd({ animated: false });
            }
          }}
        />
      )}

      <Animated.View
        className="absolute left-0 right-0 px-2 pb-5 bg-surface rounded-t-4xl"
        style={animatedInputStyle}
      >
        <ChatInput
          onSend={handleSend}
          value={inputValue}
          onChangeText={setInputValue}
        />
      </Animated.View>
    </View>
  );
}

export default function ChatScreen() {
  const { activeChatId } = useChatContext();

  const [isReady, setIsReady] = useState(false);
  const screenOpacity = useSharedValue(0);

  useEffect(() => {
    const timer = setTimeout(() => {
      setIsReady(true);
      screenOpacity.value = withTiming(1, {
        duration: 400,
        easing: Easing.out(Easing.ease),
      });
    }, 50);
    return () => clearTimeout(timer);
  }, [screenOpacity]);

  const animatedScreenStyle = useAnimatedStyle(() => ({
    opacity: screenOpacity.value,
  }));

  return (
    <ChatLayout
      background={
        !activeChatId ? (
          <>
            <Image
              source={require("@/assets/background/chat.jpg")}
              style={{ width: "100%", height: "100%", opacity: 0.65 }}
              resizeMode="cover"
            />
            <LinearGradient
              colors={[
                "rgba(0,0,0,0.3)",
                "rgba(255,255,255,0.1)",
                "rgba(0,0,0,0.0)",
                "rgba(0,0,0,0.75)",
              ]}
              locations={[0, 0.2, 0.45, 1]}
              style={{ position: "absolute", width: "100%", height: "100%" }}
            />
          </>
        ) : undefined
      }
    >
      <Animated.View className="flex-1" style={animatedScreenStyle}>
        <ChatContent activeChatId={activeChatId} />
      </Animated.View>
    </ChatLayout>
  );
}
