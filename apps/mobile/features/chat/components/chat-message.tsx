/**
 * Chat Message Component
 * Displays individual chat messages with different styles for user and AI
 */

import { Ionicons, MaterialCommunityIcons } from "@expo/vector-icons";
import * as Clipboard from "expo-clipboard";
import { useEffect, useRef, useState } from "react";
import {
  Alert,
  Animated,
  Image,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from "react-native";
import { ChatTheme } from "@/shared/constants/chat-theme";
import type { Message } from "../types";

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

  return (
    <Animated.View
      style={[
        styles.container,
        message.isUser ? styles.userContainer : styles.aiContainer,
        {
          opacity: fadeAnim,
          transform: [{ scale: scaleAnim }],
        },
      ]}
    >
      {!message.isUser && (
        <Image
          source={require("@/assets/logo/logo.webp")}
          style={styles.aiIconContainer}
          resizeMode="contain"
        />
      )}

      <View
        style={[
          styles.messageWrapper,
          message.isUser && styles.messageWrapperUser,
        ]}
      >
        <View
          style={[
            styles.messageBubble,
            message.isUser ? styles.userBubble : styles.aiBubble,
            message.isUser && styles.messageBubbleUser,
          ]}
        >
          <Text
            style={[
              styles.messageText,
              message.isUser ? styles.userText : styles.aiText,
            ]}
          >
            {message.text}
          </Text>
        </View>

        {!message.isUser && (
          <View style={styles.actionsContainer}>
            <TouchableOpacity onPress={handlePin} style={styles.actionButton}>
              <MaterialCommunityIcons
                name={isPinned ? "pin" : "pin-outline"}
                size={14}
                color={isPinned ? ChatTheme.accent : ChatTheme.iconSecondary}
              />
            </TouchableOpacity>
            <TouchableOpacity onPress={handleCopy} style={styles.actionButton}>
              <Ionicons
                name="copy-outline"
                size={14}
                color={ChatTheme.iconSecondary}
              />
            </TouchableOpacity>
          </View>
        )}
      </View>
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  container: {
    flexDirection: "row",
    marginVertical: ChatTheme.spacing.sm,
    paddingHorizontal: ChatTheme.spacing.md,
  },
  userContainer: {
    justifyContent: "flex-end",
  },
  aiContainer: {
    justifyContent: "flex-start",
    alignItems: "flex-start",
  },
  aiIconContainer: {
    width: 28,
    height: 28,
    marginRight: ChatTheme.spacing.sm,
    marginTop: 4,
  },
  messageWrapper: {
    flex: 1,
    alignItems: "flex-start",
  },
  messageWrapperUser: {
    alignItems: "flex-end",
  },
  messageBubble: {
    alignSelf: "flex-start",
    maxWidth: "100%",
    paddingHorizontal: ChatTheme.spacing.md,
    paddingVertical: ChatTheme.spacing.sm + 2,
    borderRadius: ChatTheme.borderRadius.lg,
  },
  messageBubbleUser: {
    alignSelf: "flex-end",
  },
  userBubble: {
    backgroundColor: ChatTheme.userMessage,
  },
  aiBubble: {
    backgroundColor: ChatTheme.aiMessage,
  },
  messageText: {
    fontSize: ChatTheme.fontSize.md,
    lineHeight: 20,
    fontFamily: ChatTheme.fonts.regular,
  },
  userText: {
    color: ChatTheme.background,
  },
  aiText: {
    color: ChatTheme.textPrimary,
  },
  actionsContainer: {
    flexDirection: "row",
    marginTop: 4,
    marginLeft: 2,
    gap: 4,
  },
  actionButton: {
    padding: 4,
    opacity: 0.5,
  },
});
