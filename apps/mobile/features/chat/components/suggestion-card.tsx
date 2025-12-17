/**
 * SuggestionCard Component
 * Animated card for chat suggestions with press feedback
 */

import { useEffect, useRef } from "react";
import {
  Animated,
  Image,
  StyleSheet,
  Text,
  TouchableOpacity,
} from "react-native";
import { ChatTheme } from "@/shared/constants/chat-theme";
import type { Suggestion } from "../types";

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
      style={[
        styles.wrapper,
        {
          opacity: fadeAnim,
          transform: [{ scale: scaleAnim }],
        },
      ]}
    >
      <TouchableOpacity
        style={styles.card}
        onPress={() => onPress(suggestion.text)}
        onPressIn={handlePressIn}
        onPressOut={handlePressOut}
        activeOpacity={1}
      >
        <Image
          source={{ uri: suggestion.iconUrl }}
          style={styles.icon}
          resizeMode="contain"
        />
        <Text style={styles.text}>{suggestion.text}</Text>
      </TouchableOpacity>
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  wrapper: {
    width: "48%",
  },
  card: {
    width: "100%",
    backgroundColor: "#222224",
    borderRadius: ChatTheme.borderRadius.lg,
    padding: ChatTheme.spacing.md,
    borderWidth: 1,
    borderColor: ChatTheme.border,
    minHeight: 100,
    justifyContent: "space-between",
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.3,
    shadowRadius: 8,
    elevation: 6,
  },
  icon: {
    width: 28,
    height: 28,
  },
  text: {
    fontSize: ChatTheme.fontSize.sm,
    fontFamily: ChatTheme.fonts.regular,
    color: ChatTheme.textPrimary,
    marginTop: ChatTheme.spacing.sm,
    lineHeight: 18,
  },
});
