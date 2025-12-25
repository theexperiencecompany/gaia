import { useEffect, useRef } from "react";
import { Animated, Image, Text, View } from "react-native";
import { PressableFeedback } from "heroui-native";
import type { Suggestion } from "../../types";

interface SuggestionCardProps {
  suggestion: Suggestion;
  index: number;
  onPress: (text: string) => void;
}

export function SuggestionCard({
  suggestion,
  index,
  onPress,
}: SuggestionCardProps) {
  const fadeAnim = useRef(new Animated.Value(0)).current;
  const scaleAnim = useRef(new Animated.Value(0.9)).current;

  useEffect(() => {
    Animated.parallel([
      Animated.timing(fadeAnim, {
        toValue: 1,
        duration: 400,
        delay: index * 100,
        useNativeDriver: true,
      }),
      Animated.spring(scaleAnim, {
        toValue: 1,
        tension: 80,
        friction: 8,
        delay: index * 100,
        useNativeDriver: true,
      }),
    ]).start();
  }, [fadeAnim, scaleAnim, index]);

  return (
    <Animated.View
      className="w-[48%] mb-3"
      style={{
        opacity: fadeAnim,
        transform: [{ scale: scaleAnim }],
      }}
    >
      <PressableFeedback onPress={() => onPress(suggestion.text)}>
        <View className="px-5 py-5 min-h-30 justify-between bg-surface-2 rounded-xl">
          <Image
            source={{ uri: suggestion.iconUrl }}
            className="w-8 h-8 rounded-lg opacity-80"
            resizeMode="contain"
          />
          <Text
            className="text-sm font-semibold text-foreground/80 mt-4 leading-relaxed"
            numberOfLines={2}
          >
            {suggestion.text}
          </Text>
        </View>
      </PressableFeedback>
    </Animated.View>
  );
}
