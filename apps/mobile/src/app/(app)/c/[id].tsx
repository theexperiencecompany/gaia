import { LinearGradient } from "expo-linear-gradient";
import { useLocalSearchParams } from "expo-router";
import { useEffect, useMemo } from "react";
import { Image } from "react-native";
import { ChatScreenContent } from "@/features/chat/components/chat/chat-screen-content";
import { ChatLayout } from "@/features/chat/components/chat-layout";
import { useChatContext } from "@/features/chat/hooks/use-chat-context";
import { useChatStore } from "@/stores/chat-store";

function normalizeRouteId(rawId: string | string[] | undefined): string | null {
  if (!rawId) {
    return null;
  }

  const value = Array.isArray(rawId) ? rawId[0] : rawId;
  const normalized = value.trim();

  return normalized.length > 0 ? normalized : null;
}

export default function ChatDeepLinkScreen() {
  const { id } = useLocalSearchParams<{ id?: string | string[] }>();
  const normalizedId = useMemo(() => normalizeRouteId(id), [id]);
  const { setActiveChatId } = useChatContext();
  const isTyping = useChatStore((state) => state.streamingState.isTyping);

  useEffect(() => {
    setActiveChatId(normalizedId);
  }, [normalizedId, setActiveChatId]);

  return (
    <ChatLayout
      background={
        !normalizedId && !isTyping ? (
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
      <ChatScreenContent activeChatId={normalizedId} />
    </ChatLayout>
  );
}
