import { useEffect, useRef } from "react";
import { Animated, Image, Pressable } from "react-native";
import { Card } from "@/components/ui/card";
import { Text } from "@/components/ui/text";
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
  }, []);

  const handlePressIn = () => {
    Animated.spring(scaleAnim, {
      toValue: 0.95,
      tension: 100,
      friction: 5,
      useNativeDriver: true,
    }).start();
  };

  const handlePressOut = () => {
    Animated.spring(scaleAnim, {
      toValue: 1,
      tension: 100,
      friction: 5,
      useNativeDriver: true,
    }).start();
  };

  return (
    <Animated.View
      className="w-[48%]"
      style={{
        opacity: fadeAnim,
        transform: [{ scale: scaleAnim }],
      }}
    >
      <Pressable
        onPress={() => onPress(suggestion.text)}
        onPressIn={handlePressIn}
        onPressOut={handlePressOut}
      >
        <Card className="px-5 py-5 min-h-[120px] justify-between border-transparent bg-surface-2 shadow-md">
          <Image
            source={{ uri: suggestion.iconUrl }}
            className="w-8 h-8 rounded-lg opacity-80"
            resizeMode="contain"
          />
          <Text
            className="text-[13px] font-semibold text-foreground/80 mt-4 leading-relaxed"
            numberOfLines={2}
          >
            {suggestion.text}
          </Text>
        </Card>
      </Pressable>
    </Animated.View>
  );
}
