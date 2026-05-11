import { useEffect } from "react";
import Animated, {
  Easing,
  useAnimatedStyle,
  useSharedValue,
  withTiming,
} from "react-native-reanimated";
import { ChatScreenContent } from "@/features/chat/components/chat/chat-screen-content";
import { ChatLayout } from "@/features/chat/components/chat-layout";
import { useChatContext } from "@/features/chat/hooks/use-chat-context";

export default function ChatScreen() {
  const { activeChatId } = useChatContext();

  const screenOpacity = useSharedValue(0);

  useEffect(() => {
    const timer = setTimeout(() => {
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
    <ChatLayout>
      <Animated.View style={[{ flex: 1 }, animatedScreenStyle]}>
        <ChatScreenContent activeChatId={activeChatId} />
      </Animated.View>
    </ChatLayout>
  );
}
