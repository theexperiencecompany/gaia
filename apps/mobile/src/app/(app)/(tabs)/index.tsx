import { LinearGradient } from "expo-linear-gradient";
import { useEffect, useState } from "react";
import { Image } from "react-native";
import Animated, {
  Easing,
  useAnimatedStyle,
  useSharedValue,
  withTiming,
} from "react-native-reanimated";
import { ChatScreenContent } from "@/features/chat/components/chat/chat-screen-content";
import { ChatLayout } from "@/features/chat/components/chat-layout";
import { useChatContext } from "@/features/chat/hooks/use-chat-context";
import { useChatStore } from "@/stores/chat-store";

export default function ChatScreen() {
  const { activeChatId } = useChatContext();
  const isTyping = useChatStore((state) => state.streamingState.isTyping);

  const [_isReady, setIsReady] = useState(false);
  const screenOpacity = useSharedValue(0);

  useEffect(() => {
    const timer = setTimeout(() => {
      setIsReady(true);
      screenOpacity.value = withTiming(1, {
        duration: 400,
        easing: Easing.out(Easing.ease),
      });
    }, 50);
    return () => clearTimeout(timer);
  }, [screenOpacity]);

  const animatedScreenStyle = useAnimatedStyle(() => ({
    opacity: screenOpacity.value,
  }));

  return (
    <ChatLayout
      background={
        !activeChatId && !isTyping ? (
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
      <Animated.View style={[{ flex: 1 }, animatedScreenStyle]}>
        <ChatScreenContent activeChatId={activeChatId} />
      </Animated.View>
    </ChatLayout>
  );
}
