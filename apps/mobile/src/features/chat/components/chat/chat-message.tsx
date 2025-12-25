import * as Clipboard from "expo-clipboard";
import { useEffect, useRef, useState } from "react";
import { Alert, Animated, Image, Text, View } from "react-native";
import { PressableFeedback } from "heroui-native";
import { Copy01Icon, HugeiconsIcon, PinIcon } from "@/components/icons";
import type { Message } from "../../types";

interface ChatMessageProps {
  message: Message;
}

export function ChatMessage({ message }: ChatMessageProps) {
  const [isPinned, setIsPinned] = useState(false);
  const fadeAnim = useRef(new Animated.Value(0)).current;
  const scaleAnim = useRef(new Animated.Value(0.95)).current;

  useEffect(() => {
    Animated.parallel([
      Animated.timing(fadeAnim, {
        toValue: 1,
        duration: 300,
        useNativeDriver: true,
      }),
      Animated.spring(scaleAnim, {
        toValue: 1,
        tension: 100,
        friction: 8,
        useNativeDriver: true,
      }),
    ]).start();
  }, [fadeAnim, scaleAnim]);

  const handleCopy = async () => {
    await Clipboard.setStringAsync(message.text);
    Alert.alert("Copied", "Message copied to clipboard");
  };

  const handlePin = () => {
    setIsPinned(!isPinned);
  };

  const isUser = message.isUser;

  return (
    <Animated.View
      className={`flex-row py-6 px-6 ${isUser ? "justify-end" : "justify-start items-start"}`}
      style={{
        opacity: fadeAnim,
        transform: [{ scale: scaleAnim }],
      }}
    >
      {!isUser && (
        <Image
          source={require("@/assets/logo/logo.webp")}
          className="w-7 h-7 mr-3 mt-1"
          resizeMode="contain"
        />
      )}

      <View className={`max-w-[85%] ${isUser ? "items-end" : "items-start"}`}>
        <View
          className={`px-5 py-4 ${
            isUser
              ? "bg-accent rounded-3xl rounded-tr-sm"
              : "bg-surface-2 rounded-3xl rounded-tl-sm"
          } shadow-sm`}
        >
          <Text
            className={`text-base leading-5 ${
              isUser ? "text-accent-foreground" : "text-foreground"
            }`}
          >
            {message.text}
          </Text>
        </View>

        {/* Message Actions */}
        {!isUser && (
          <View className="mt-4 flex-row items-center gap-4 opacity-40">
            <PressableFeedback onPress={handleCopy}>
              <View className="flex-row items-center gap-1.5">
                <HugeiconsIcon icon={Copy01Icon} size={14} color="#ffffff" />
                <Text className="text-xs font-bold uppercase tracking-wider text-foreground">
                  Copy
                </Text>
              </View>
            </PressableFeedback>
            <PressableFeedback onPress={handlePin}>
              <View className="flex-row items-center gap-1.5">
                <HugeiconsIcon
                  icon={PinIcon}
                  size={14}
                  color="#ffffff"
                  fill={isPinned ? "#ffffff" : "none"}
                />
                <Text className="text-xs font-bold uppercase tracking-wider text-foreground">
                  Pin
                </Text>
              </View>
            </PressableFeedback>
          </View>
        )}
      </View>
    </Animated.View>
  );
}
