/**
 * Chat Input Component
 * Text input with send button for user messages
 */

import { ChatTheme } from '@/shared/constants/chat-theme';
import { Ionicons } from '@expo/vector-icons';
import React, { useEffect, useRef, useState } from 'react';
import { Animated, StyleSheet, Text, TextInput, TouchableOpacity, View } from 'react-native';

interface ChatInputProps {
  onSend: (message: string) => void;
  placeholder?: string;
}

export function ChatInput({ onSend, placeholder = "What can I do for you today?" }: ChatInputProps) {
  const [message, setMessage] = useState('');
  const scaleAnim = useRef(new Animated.Value(1)).current;
  const [isFocused, setIsFocused] = useState(false);

  useEffect(() => {
    Animated.spring(scaleAnim, {
      toValue: message.trim() ? 1 : 0.9,
      tension: 100,
      friction: 7,
      useNativeDriver: true,
    }).start();
  }, [message]);

  const handleSend = () => {
    if (message.trim()) {
      onSend(message.trim());
      setMessage('');
    }
  };

  return (
    <View style={styles.container}>
      <View style={[
        styles.inputContainer,
        isFocused && styles.inputContainerFocused,
      ]}>
        <TouchableOpacity style={styles.plusButton}>
          <Ionicons name="add" size={24} color={ChatTheme.iconSecondary} />
        </TouchableOpacity>
        
        <TextInput
          style={styles.input}
          value={message}
          onChangeText={setMessage}
          placeholder={placeholder}
          placeholderTextColor={ChatTheme.textSecondary}
          multiline
          maxLength={1000}
          returnKeyType="send"
          onSubmitEditing={handleSend}
          onFocus={() => setIsFocused(true)}
          onBlur={() => setIsFocused(false)}
        />
          
        <Animated.View style={{ transform: [{ scale: scaleAnim }] }}>
          <TouchableOpacity
            style={[
              styles.sendButton,
              !message.trim() && styles.sendButtonDisabled,
            ]}
            onPress={handleSend}
            disabled={!message.trim()}
            activeOpacity={0.8}
          >
            <Text style={styles.sendIcon}>↑</Text>
          </TouchableOpacity>
        </Animated.View>
      </View>
    </View>
  );
}const styles = StyleSheet.create({
  container: {
    paddingHorizontal: ChatTheme.spacing.md,
    paddingVertical: ChatTheme.spacing.md,
    backgroundColor: ChatTheme.background,
    borderTopWidth: 1,
    borderTopColor: ChatTheme.border,
  },
  inputContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: ChatTheme.inputBackground,
    borderRadius: ChatTheme.borderRadius.lg,
    borderWidth: 1,
    borderColor: ChatTheme.border,
    paddingHorizontal: ChatTheme.spacing.sm,
    paddingVertical: ChatTheme.spacing.xs,
    minHeight: 48,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.1,
    shadowRadius: 4,
    elevation: 3,
  },
  inputContainerFocused: {
    borderColor: ChatTheme.accent,
    shadowOpacity: 0.2,
    shadowRadius: 8,
    elevation: 5,
  },
  plusButton: {
    padding: ChatTheme.spacing.xs,
    marginRight: ChatTheme.spacing.xs,
  },
  input: {
    flex: 1,
    color: ChatTheme.textPrimary,
    fontSize: ChatTheme.fontSize.md,
    maxHeight: 100,
    paddingVertical: 8,
    fontFamily: ChatTheme.fonts.regular,
  },
  sendButton: {
    width: 32,
    height: 32,
    borderRadius: 16,
    backgroundColor: ChatTheme.accent,
    justifyContent: 'center',
    alignItems: 'center',
    marginLeft: ChatTheme.spacing.sm,
    shadowColor: ChatTheme.accent,
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.4,
    shadowRadius: 4,
    elevation: 4,
  },
  sendButtonDisabled: {
    backgroundColor: ChatTheme.iconSecondary,
    opacity: 0.4,
    shadowOpacity: 0,
  },
  sendIcon: {
    fontSize: 20,
    color: ChatTheme.background,
    fontWeight: 'bold',
  },
});
