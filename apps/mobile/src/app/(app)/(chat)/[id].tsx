import { useLocalSearchParams, useRouter } from "expo-router";
import { useCallback, useEffect, useState } from "react";
import { FlashList } from "@shopify/flash-list";
import { Keyboard, View } from "react-native";
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

export default function ChatPage() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const { setActiveChatId } = useChatContext();

  useEffect(() => {
    if (id) {
      setActiveChatId(id);
    }
  }, [id, setActiveChatId]);

  const {
    messages,
    isTyping,
    progress,
    flatListRef,
    sendMessage,
    scrollToBottom,
  } = useChat(id || null);

  useEffect(() => {
    console.log("[ChatPage] isTyping:", isTyping, "progress:", progress);
  }, [isTyping, progress]);

  const { drawerRef, closeSidebar, toggleSidebar } = useSidebar();
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

  const handleSelectChat = (chatId: string) => {
    setActiveChatId(chatId);
    closeSidebar();
    router.replace(`/(chat)/${chatId}`);
  };

  const handleNewChat = () => {
    closeSidebar();
    setActiveChatId(null);
    router.replace("/");
  };

  const handleFollowUpAction = useCallback((action: string) => {
    setInputValue(action);
  }, []);

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
          onFollowUpAction={handleFollowUpAction}
          isLoading={showLoading}
          loadingMessage={showLoading ? displayMessage : undefined}
        />
      );
    },
    [handleFollowUpAction, messages.length, isTyping, displayMessage]
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
              <View style={{ flex: 1 }}>
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
              </View>

              <Animated.View
                className="absolute left-0 right-0 px-2 pb-2 bg-surface rounded-t-4xl"
                style={animatedInputStyle}
              >
                <ChatInput
                  onSend={(msg) => {
                    setLastUserMessage(msg);
                    sendMessage(msg);
                    setInputValue("");
                  }}
                  value={inputValue}
                  onChangeText={setInputValue}
                />
              </Animated.View>
            </View>
          </SafeAreaView>
        </View>
      </DrawerLayout>
    </View>
  );
}
