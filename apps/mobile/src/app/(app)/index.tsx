import { useRouter } from "expo-router";
import { useCallback, useEffect, useState } from "react";
import { FlashList } from "@shopify/flash-list";
import { Keyboard, Text, View } from "react-native";
import DrawerLayout, {
  DrawerPosition,
  DrawerState,
  DrawerType,
} from "react-native-gesture-handler/ReanimatedDrawerLayout";
import Animated, {
  runOnJS,
  useAnimatedKeyboard,
  useAnimatedReaction,
  useAnimatedStyle,
} from "react-native-reanimated";
import { SafeAreaView } from "react-native-safe-area-context";
import { ChatInput } from "@/components/ui/chat-input";
import {
  ChatHeader,
  ChatMessage,
  type Message,
  SIDEBAR_WIDTH,
  SidebarContent,
  useChat,
  useChatContext,
  useSidebar,
} from "@/features/chat";
import { getRelevantThinkingMessage } from "@/features/chat/utils/playfulThinking";

export default function IndexScreen() {
  const router = useRouter();
  const { setActiveChatId } = useChatContext();
  const { drawerRef, closeSidebar, toggleSidebar } = useSidebar();

  const keyboard = useAnimatedKeyboard();

  const animatedContainerStyle = useAnimatedStyle(() => ({
    transform: [{ translateY: -keyboard.height.value }],
  }));

  const animatedInputContainerStyle = useAnimatedStyle(() => ({
    paddingBottom: 6,
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

  const handleSelectChat = (chatId: string) => {
    setActiveChatId(chatId);
    closeSidebar();
    router.push(`/(chat)/${chatId}`);
  };

  const handleNewChat = () => {
    closeSidebar();
    setActiveChatId(null);
  };

  const handleSendMessage = async (text: string) => {
    setLastUserMessage(text);
    await sendMessage(text);
  };

  const renderDrawerContent = () => (
    <SidebarContent onSelectChat={handleSelectChat} onNewChat={handleNewChat} />
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
          isLoading={showLoading}
          loadingMessage={showLoading ? displayMessage : undefined}
        />
      );
    },
    [messages.length, isTyping, displayMessage]
  );

  return (
    <View className="flex-1">
      <DrawerLayout
        ref={drawerRef}
        drawerWidth={SIDEBAR_WIDTH}
        drawerPosition={DrawerPosition.LEFT}
        drawerType={DrawerType.FRONT}
        overlayColor="rgba(0, 0, 0, 0.7)"
        renderNavigationView={renderDrawerContent}
        onDrawerStateChanged={(newState) => {
          if (newState !== DrawerState.IDLE) Keyboard.dismiss();
        }}
      >
        <View className="flex-1">
          <SafeAreaView style={{ flex: 1 }} edges={["top"]}>
            <ChatHeader
              onMenuPress={toggleSidebar}
              onNewChatPress={handleNewChat}
              onSearchPress={() => console.log("Search pressed")}
            />

            <View style={{ flex: 1, overflow: "hidden" }}>
              <Animated.View style={[{ flex: 1 }, animatedContainerStyle]}>
                <View style={{ flex: 1 }}>
                  {messages.length === 0 && !isTyping ? (
                    <View className="flex-1 items-center justify-center px-6">
                      <Text className="text-2xl font-semibold text-foreground mb-2">
                        What can I help you with?
                      </Text>
                      <Text className="text-default-500 text-center">
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
                </View>

                <Animated.View
                  className="px-2 bg-surface rounded-t-4xl"
                  style={animatedInputContainerStyle}
                >
                  <ChatInput onSend={handleSendMessage} />
                </Animated.View>
              </Animated.View>
            </View>
          </SafeAreaView>
        </View>
      </DrawerLayout>
    </View>
  );
}
