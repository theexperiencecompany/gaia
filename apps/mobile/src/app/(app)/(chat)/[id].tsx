import { useLocalSearchParams } from "expo-router";
import { useEffect } from "react";
import {
  FlatList,
  Keyboard,
  KeyboardAvoidingView,
  Platform,
  TouchableWithoutFeedback,
  View,
} from "react-native";
import { GestureHandlerRootView } from "react-native-gesture-handler";
import DrawerLayout, {
  DrawerPosition,
  DrawerType,
} from "react-native-gesture-handler/ReanimatedDrawerLayout";
import { SafeAreaView } from "react-native-safe-area-context";
import {
  ChatEmptyState,
  ChatHeader,
  ChatInput,
  ChatMessage,
  DEFAULT_SUGGESTIONS,
  type Message,
  SIDEBAR_WIDTH,
  SidebarContent,
  useChat,
  useChatContext,
  useSidebar,
} from "@/features/chat";

export default function ChatPage() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { activeChatId, setActiveChatId, createNewChat } = useChatContext();

  useEffect(() => {
    if (id && id !== activeChatId) {
      setActiveChatId(id);
    }
  }, [id, activeChatId, setActiveChatId]);

  const { messages, isTyping, flatListRef, sendMessage, scrollToBottom } =
    useChat(activeChatId);

  const { drawerRef, closeSidebar, toggleSidebar } = useSidebar();

  useEffect(() => {
    scrollToBottom();
  }, [messages.length, scrollToBottom]);

  const handleSelectChat = (chatId: string) => {
    setActiveChatId(chatId);
    closeSidebar();
  };

  const handleNewChat = () => {
    createNewChat();
    closeSidebar();
  };

  const renderDrawerContent = () => (
    <SidebarContent onSelectChat={handleSelectChat} onNewChat={handleNewChat} />
  );

  const renderMessage = ({ item }: { item: Message }) => (
    <ChatMessage message={item} />
  );

  const renderEmpty = () => (
    <ChatEmptyState
      suggestions={DEFAULT_SUGGESTIONS}
      onSuggestionPress={sendMessage}
    />
  );

  return (
    <GestureHandlerRootView className="flex-1">
      <DrawerLayout
        ref={drawerRef}
        drawerWidth={SIDEBAR_WIDTH}
        drawerPosition={DrawerPosition.LEFT}
        drawerType={DrawerType.FRONT}
        overlayColor="rgba(0, 0, 0, 0.7)"
        renderNavigationView={renderDrawerContent}
      >
        <KeyboardAvoidingView
          className="flex-1 bg-surface-1"
          behavior={Platform.OS === "ios" ? "padding" : "height"}
          keyboardVerticalOffset={Platform.OS === "ios" ? 0 : 0}
        >
          <SafeAreaView
            className="flex-1 bg-surface-1"
            edges={["top", "bottom"]}
          >
            {/* Header */}
            <ChatHeader
              onMenuPress={toggleSidebar}
              onNewChatPress={handleNewChat}
              onSearchPress={() => console.log("Search pressed")}
            />

            {/* Messages List */}
            <TouchableWithoutFeedback onPress={Keyboard.dismiss}>
              <View className="flex-1">
                <FlatList
                  ref={flatListRef}
                  data={messages}
                  renderItem={renderMessage}
                  keyExtractor={(item) => item.id}
                  contentContainerStyle={{ flexGrow: 1, paddingBottom: 32 }}
                  ListEmptyComponent={renderEmpty}
                  showsVerticalScrollIndicator={false}
                  keyboardShouldPersistTaps="handled"
                />
              </View>
            </TouchableWithoutFeedback>

            {/* Bottom Input & Typing Indicator */}
            <View className="w-full bg-surface-1/95 border-t border-border/10 px-6 pb-8 pt-4">
              {isTyping && (
                <View className="flex-row items-center px-2 py-3 gap-2 mb-2">
                  <View className="w-1.5 h-1.5 rounded-full bg-primary/60" />
                  <View className="w-1.5 h-1.5 rounded-full bg-primary/60" />
                  <View className="w-1.5 h-1.5 rounded-full bg-primary/60" />
                </View>
              )}
              <ChatInput placeholder="What can I do for you today?" />
            </View>
          </SafeAreaView>
        </KeyboardAvoidingView>
      </DrawerLayout>
    </GestureHandlerRootView>
  );
}
