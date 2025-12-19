import * as Clipboard from "expo-clipboard";
import { useEffect, useRef, useState } from "react";
import { Alert, Animated, Image, TouchableOpacity, View } from "react-native";
import { Copy01Icon, HugeiconsIcon, PinIcon } from "@/components/icons";
import { Text } from "@/components/ui/text";
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
  }, []);

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
              ? "bg-primary rounded-3xl rounded-tr-sm"
              : "bg-surface-2 rounded-3xl rounded-tl-sm"
          } shadow-sm`}
        >
          <Text
            className={`text-base leading-5 ${
              isUser ? "text-black" : "text-white"
            }`}
          >
            {message.text}
          </Text>
        </View>

        {/* Message Content */}
        {!isUser && (
          <View className="mt-4 flex-row items-center gap-4 opacity-40">
            <TouchableOpacity
              className="flex-row items-center gap-1.5"
              onPress={handleCopy}
              activeOpacity={0.6}
            >
              <HugeiconsIcon icon={Copy01Icon} size={14} color="#ffffff" />
              <Text className="text-[10px] font-bold uppercase tracking-wider text-white">
                Copy
              </Text>
            </TouchableOpacity>
            <TouchableOpacity
              className="flex-row items-center gap-1.5"
              onPress={handlePin}
              activeOpacity={0.6}
            >
              <HugeiconsIcon
                icon={PinIcon}
                size={14}
                color="#ffffff"
                fill={isPinned ? "#ffffff" : "none"}
              />
              <Text className="text-[10px] font-bold uppercase tracking-wider text-white">
                Pin
              </Text>
            </TouchableOpacity>
          </View>
        )}
      </View>
    </Animated.View>
  );
}
