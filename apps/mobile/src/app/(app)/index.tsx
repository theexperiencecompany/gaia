import { useRouter } from "expo-router";
import { useEffect } from "react";
import { KeyboardAvoidingView, Platform, Text, View } from "react-native";
import DrawerLayout, {
  DrawerPosition,
  DrawerType,
} from "react-native-gesture-handler/ReanimatedDrawerLayout";
import { SafeAreaView } from "react-native-safe-area-context";
import {
  ChatHeader,
  SIDEBAR_WIDTH,
  SidebarContent,
  useChat,
  useChatContext,
  useSidebar,
} from "@/features/chat";
import { ChatInput } from "@/components/ui/chat-input";

export default function IndexScreen() {
  const router = useRouter();
  const { setActiveChatId, createNewChat } = useChatContext();

  // Use "new" as the chatId for the empty state
  const { isTyping, sendMessage, newConversationId } = useChat("new");

  const { drawerRef, closeSidebar, toggleSidebar } = useSidebar();

  // Redirect when a new conversation is created
  useEffect(() => {
    if (newConversationId) {
      setActiveChatId(newConversationId);
      router.replace(`/(chat)/${newConversationId}`);
    }
  }, [newConversationId, router, setActiveChatId]);

  const handleSelectChat = (chatId: string) => {
    setActiveChatId(chatId);
    closeSidebar();
    router.push(`/(chat)/${chatId}`);
  };

  const handleNewChat = () => {
    createNewChat();
    closeSidebar();
  };

  const renderDrawerContent = () => (
    <SidebarContent onSelectChat={handleSelectChat} onNewChat={handleNewChat} />
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

            {/* Empty chat area with welcome message */}
            <View className="flex-1 items-center justify-center px-6">
              <Text className="text-2xl font-semibold text-foreground mb-2">
                What can I help you with?
              </Text>
              <Text className="text-default-500 text-center">
                Start a conversation by typing a message below
              </Text>
            </View>

            <View className="px-2 pb-2 bg-surface rounded-t-4xl">
              {isTyping && (
                <View className="flex-row items-center px-2 py-3 gap-2 mb-2">
                  <View className="w-1.5 h-1.5 rounded-full bg-primary/60" />
                  <View className="w-1.5 h-1.5 rounded-full bg-primary/60" />
                  <View className="w-1.5 h-1.5 rounded-full bg-primary/60" />
                </View>
              )}
              <ChatInput onSend={sendMessage} />
            </View>
          </SafeAreaView>
        </KeyboardAvoidingView>
      </DrawerLayout>
    </View>
  );
}
