import { useRouter } from "expo-router";
import { useCallback, useEffect, useState } from "react";
import { FlashList } from "@shopify/flash-list";
import { Image, Keyboard, Pressable, View } from "react-native";
import { Text } from "@/components/ui/text";
import { LinearGradient } from "expo-linear-gradient";
import DrawerLayout, {
  DrawerPosition,
  DrawerState,
  DrawerType,
} from "react-native-gesture-handler/ReanimatedDrawerLayout";
import Animated, {
  FadeIn,
  FadeInDown,
  FadeInUp,
  runOnJS,
  useAnimatedKeyboard,
  useAnimatedReaction,
  useAnimatedStyle,
  useSharedValue,
  withDelay,
  withSpring,
  withTiming,
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

  // Entrance animations
  const backgroundOpacity = useSharedValue(0);
  const headerOpacity = useSharedValue(0);
  const contentScale = useSharedValue(0.9);
  const contentOpacity = useSharedValue(0);
  const inputOpacity = useSharedValue(0);
  const inputScale = useSharedValue(0.95);

  useEffect(() => {
    // Staggered entrance animations
    backgroundOpacity.value = withTiming(1, { duration: 800 });
    headerOpacity.value = withDelay(200, withTiming(1, { duration: 600 }));
    contentOpacity.value = withDelay(400, withTiming(1, { duration: 600 }));
    contentScale.value = withDelay(400, withSpring(1, { damping: 15, stiffness: 100 }));
    inputOpacity.value = withDelay(500, withTiming(1, { duration: 400 }));
    inputScale.value = withDelay(500, withSpring(1, { damping: 20, stiffness: 150 }));
  }, []);

  const animatedBackgroundStyle = useAnimatedStyle(() => ({
    opacity: backgroundOpacity.value * 0.65,
  }));

  const animatedHeaderStyle = useAnimatedStyle(() => ({
    opacity: headerOpacity.value,
  }));

  const animatedContentStyle = useAnimatedStyle(() => ({
    opacity: contentOpacity.value,
    transform: [{ scale: contentScale.value }],
  }));

  const animatedInputStyle = useAnimatedStyle(() => ({
    opacity: inputOpacity.value,
    transform: [{ scale: inputScale.value }],
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
      <Animated.Image
        source={require("@/assets/background/chat.jpg")}
        className="absolute w-full h-full"
        style={animatedBackgroundStyle}
        resizeMode="cover"
      />
      <Animated.View 
        style={[{ position: 'absolute', width: '100%', height: '100%' }, animatedBackgroundStyle]}
      >
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
      </Animated.View>

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
            <Animated.View style={animatedHeaderStyle}>
              <ChatHeader
                onMenuPress={toggleSidebar}
                onNewChatPress={handleNewChat}
                onSearchPress={() => console.log("Search pressed")}
              />
            </Animated.View>

            <View style={{ flex: 1, overflow: "hidden" }}>
              <Animated.View style={[{ flex: 1 }, animatedContainerStyle]}>
                <Pressable style={{ flex: 1 }} onPress={Keyboard.dismiss}>
                  {messages.length === 0 && !isTyping ? (
                    <Animated.View 
                      className="flex-1 items-center justify-center px-6"
                      style={animatedContentStyle}
                    >
                      <Text variant={"h2"} className="">
                        What can I help you with?
                      </Text>
                      <Text className="text-xs">
                        Start a conversation by typing a message below
                      </Text>
                    </Animated.View>
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
                  className="px-2 pb-5 bg-surface rounded-t-4xl border border-white/30 border-b-0"
                  style={animatedInputStyle}
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
