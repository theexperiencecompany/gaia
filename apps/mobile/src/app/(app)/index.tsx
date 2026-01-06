import { useRouter } from "expo-router";
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

export default function IndexScreen() {
  const router = useRouter();
  const { setActiveChatId } = useChatContext();

  const keyboard = useAnimatedKeyboard();

  const animatedInputStyle = useAnimatedStyle(() => ({
    bottom: keyboard.height.value,
  }));

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
  }, []);

  const animatedScreenStyle = useAnimatedStyle(() => ({
    opacity: screenOpacity.value,
  }));

  const {
    messages,
    isTyping,
    progress,
    conversationId,
    flatListRef,
    sendMessage,
    scrollToBottom,
  } = useChat(null, {
    onNavigate: (newConversationId) => {
      router.replace(`/(chat)/${newConversationId}`);
    },
  });

  const [lastUserMessage, setLastUserMessage] = useState("");
  const [thinkingMessage, setThinkingMessage] = useState(() =>
    getRelevantThinkingMessage("")
  );

  useEffect(() => {
    if (conversationId) {
      setActiveChatId(conversationId);
    }
  }, [conversationId, setActiveChatId]);

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

  const handleSendMessage = async (text: string) => {
    setLastUserMessage(text);
    await sendMessage(text);
  };

  const renderMessage = useCallback(
    ({ item, index }: { item: Message; index: number }) => {
      const isLastMessage = index === messages.length - 1;
      const isEmptyAiMessage =
        !item.isUser && (!item.text || item.text.trim() === "");
      const showLoading = isLastMessage && isEmptyAiMessage && isTyping;

      return (
        <ChatMessage
          message={item}
          isLoading={showLoading}
          loadingMessage={showLoading ? displayMessage : undefined}
        />
      );
    },
    [messages.length, isTyping, displayMessage]
  );

  return (
    <ChatLayout>
      <Animated.View className="flex-1" style={animatedScreenStyle}>
        <Image
          source={require("@/assets/background/chat.jpg")}
          className="absolute w-full h-full opacity-65"
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
          className="absolute w-full h-full"
        />

        <View style={{ flex: 1, overflow: "hidden" }}>
          <Pressable style={{ flex: 1 }} onPress={Keyboard.dismiss}>
            {messages.length === 0 && !isTyping ? (
              <View className="flex-1 items-center justify-center px-6">
                <Text variant={"h2"} className="">
                  What can I help you with?
                </Text>
                <Text className="text-xs">
                  Start a conversation by typing a message below
                </Text>
              </View>
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
          </Pressable>

          <Animated.View
            className="absolute left-0 right-0 px-2 pb-5 bg-surface rounded-t-4xl border border-white/30 border-b-0"
            style={animatedInputStyle}
          >
            <ChatInput onSend={handleSendMessage} />
          </Animated.View>
        </View>
      </Animated.View>
    </ChatLayout>
  );
}
