import { useLocalSearchParams } from "expo-router";
import { useEffect } from "react";
import {
  ActivityIndicator,
  FlatList,
  Keyboard,
  KeyboardAvoidingView,
  Platform,
  Text,
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

  // Set active chat ID when navigating to this page
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (id) {
      setActiveChatId(id);
    }
  }, [id]); // Only depend on id, not activeChatId

  const {
    messages,
    isTyping,
    isLoading,
    flatListRef,
    sendMessage,
    scrollToBottom,
  } = useChat(activeChatId);

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

  const renderEmpty = () => {
    if (isLoading) {
      return (
        <View className="flex-1 items-center justify-center">
          <ActivityIndicator size="large" color="#16c1ff" />
          <Text className="text-muted-foreground mt-4 text-sm">
            Loading messages...
          </Text>
        </View>
      );
    }

    return (
      <ChatEmptyState
        suggestions={DEFAULT_SUGGESTIONS}
        onSuggestionPress={sendMessage}
      />
    );
  };

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
            style={{ flex: 1, backgroundColor: "#141414" }}
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
                  contentContainerStyle={{
                    flexGrow: 1,
                    paddingTop: 16,
                    paddingBottom: 32,
                  }}
                  ListEmptyComponent={renderEmpty}
                  showsVerticalScrollIndicator={true}
                  keyboardShouldPersistTaps="handled"
                  initialNumToRender={20}
                  maxToRenderPerBatch={10}
                  windowSize={10}
                  onContentSizeChange={() => {
                    if (messages.length > 0) {
                      flatListRef.current?.scrollToEnd({ animated: false });
                    }
                  }}
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
