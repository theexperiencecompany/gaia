import { FlashList } from "@shopify/flash-list";
import { LinearGradient } from "expo-linear-gradient";
import { useCallback, useEffect, useState } from "react";
import {
  Image,
  Keyboard,
  KeyboardAvoidingView,
  LayoutAnimation,
  Platform,
  Pressable,
  ScrollView,
  UIManager,
  View,
} from "react-native";
import Animated, {
  Easing,
  useAnimatedStyle,
  useSharedValue,
  withTiming,
} from "react-native-reanimated";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { ChatInput } from "@/components/ui/chat-input";
import { Text } from "@/components/ui/text";
import {
  ChatLayout,
  ChatMessage,
  type Message,
  useChat,
  useChatContext,
} from "@/features/chat";
import { getRelevantThinkingMessage } from "@/features/chat/utils/playfulThinking";
import { useResponsive } from "@/lib/responsive";
import { useChatStore } from "@/stores/chat-store";

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

  const { spacing, moderateScale } = useResponsive();
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
    const setupLayoutAnimations = () => {
      if (
        Platform.OS === "android" &&
        UIManager.setLayoutAnimationEnabledExperimental
      ) {
        UIManager.setLayoutAnimationEnabledExperimental(true);
      }
    };

    setupLayoutAnimations();

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

  const handleFollowUpAction = useCallback(
    (action: string) => {
      setInputValue(action);
      onFollowUpAction?.(action);
    },
    [onFollowUpAction],
  );

  const handleSend = useCallback(
    (text: string) => {
      setLastUserMessage(text);
      sendMessage(text);
      setInputValue("");
    },
    [sendMessage],
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
    [handleFollowUpAction, messages.length, isTyping, displayMessage],
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
            backgroundColor: "#1c1c1e",
            borderTopLeftRadius: moderateScale(24, 0.5),
            borderTopRightRadius: moderateScale(24, 0.5),
          }}
        >
          <ChatInput
            onSend={handleSend}
            value={inputValue}
            onChangeText={setInputValue}
          />
        </View>
      </View>
    </KeyboardAvoidingView>
  );
}

export default function ChatScreen() {
  const { activeChatId } = useChatContext();
  const isTyping = useChatStore((state) => state.streamingState.isTyping);

  const [_isReady, setIsReady] = useState(false);
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
        !activeChatId && !isTyping ? (
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
      <Animated.View style={[{ flex: 1 }, animatedScreenStyle]}>
        <ChatContent activeChatId={activeChatId} />
      </Animated.View>
    </ChatLayout>
  );
}
