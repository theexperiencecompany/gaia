import { useLocalSearchParams, useRouter } from "expo-router";
import { useCallback, useEffect, useState } from "react";
import {
  FlatList,
  Keyboard,
  KeyboardAvoidingView,
  Platform,
  View,
} from "react-native";
import DrawerLayout, {
  DrawerPosition,
  DrawerType,
} from "react-native-gesture-handler/ReanimatedDrawerLayout";
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
  const { setActiveChatId, createNewChat } = useChatContext();

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
    getRelevantThinkingMessage(""),
  );

  // Rotate playful thinking messages when typing but no tool progress
  useEffect(() => {
    if (isTyping && !progress) {
      // Set initial message immediately
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

  // Get the display message for loading state - use progress when available, otherwise use thinking message
  const displayMessage = progress || thinkingMessage;

  useEffect(() => {
    scrollToBottom();
  }, [messages.length, scrollToBottom]);

  const handleSelectChat = (chatId: string) => {
    setActiveChatId(chatId);
    closeSidebar();
    // Use replace instead of push to avoid stacking pages
    router.replace(`/(chat)/${chatId}`);
  };

  const handleNewChat = () => {
    createNewChat();
    closeSidebar();
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
    [handleFollowUpAction, messages.length, isTyping, displayMessage],
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
      >
        <KeyboardAvoidingView
          className="flex-1"
          behavior={Platform.OS === "ios" ? "padding" : "height"}
          keyboardVerticalOffset={Platform.OS === "ios" ? 0 : 0}
        >
          <SafeAreaView style={{ flex: 1 }} edges={["top"]}>
            <ChatHeader
              onMenuPress={toggleSidebar}
              onNewChatPress={handleNewChat}
              onSearchPress={() => console.log("Search pressed")}
            />

            <View className="flex-1">
              <FlatList
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
                  flexGrow: 1,
                  paddingTop: 16,
                  paddingBottom: 32,
                }}
                showsVerticalScrollIndicator={true}
                keyboardShouldPersistTaps="handled"
                initialNumToRender={20}
                maxToRenderPerBatch={10}
                windowSize={10}
                keyboardDismissMode="on-drag"
                onScrollBeginDrag={Keyboard.dismiss}
                onContentSizeChange={() => {
                  if (messages.length > 0) {
                    flatListRef.current?.scrollToEnd({ animated: false });
                  }
                }}
              />
            </View>

            <View className="px-2 pb-2 bg-surface rounded-t-4xl">
              <ChatInput
                onSend={(msg) => {
                  setLastUserMessage(msg);
                  sendMessage(msg);
                  setInputValue("");
                }}
                value={inputValue}
                onChangeText={setInputValue}
              />
            </View>
          </SafeAreaView>
        </KeyboardAvoidingView>
      </DrawerLayout>
    </View>
  );
}
