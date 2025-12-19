import { useRouter } from "expo-router";
import { useEffect } from "react";
import { ActivityIndicator, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useChatContext } from "@/features/chat";

export default function IndexScreen() {
  const router = useRouter();
  const { activeChatId, createNewChat } = useChatContext();

  useEffect(() => {
    // Create new chat if none exists, or redirect to active chat
    const chatId = activeChatId || createNewChat();
    router.replace(`/(chat)/${chatId}`);
  }, [activeChatId, createNewChat, router]);

  return (
    <SafeAreaView className="flex-1 bg-[#0a1929]">
      <View className="flex-1 justify-center items-center">
        <ActivityIndicator size="large" color="#16c1ff" />
      </View>
    </SafeAreaView>
  );
}
