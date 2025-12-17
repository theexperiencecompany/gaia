/**
 * Home/Index Route - app/index.tsx
 * Main entry point - redirects to active or new chat
 */

import { useRouter } from "expo-router";
import { useEffect } from "react";
import { ActivityIndicator, StyleSheet, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useChatContext } from "@/features/chat";
import { ChatTheme } from "@/shared/constants/chat-theme";

export default function IndexScreen() {
  const router = useRouter();
  const { activeChatId, createNewChat } = useChatContext();

  useEffect(() => {
    // Create new chat if none exists, or redirect to active chat
    const chatId = activeChatId || createNewChat();
    router.replace(`/(chat)/${chatId}`);
  }, [activeChatId, createNewChat, router]);

  return (
    <SafeAreaView style={styles.container}>
      <View style={styles.loading}>
        <ActivityIndicator size="large" color={ChatTheme.accent} />
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: ChatTheme.background,
  },
  loading: {
    flex: 1,
    justifyContent: "center",
    alignItems: "center",
  },
});
