/**
 * ChatHeader Component
 * Top navigation bar with menu, model selector, and actions
 */

import { ChatTheme } from '@/shared/constants/chat-theme';
import { Ionicons } from '@expo/vector-icons';
import React, { useState } from 'react';
import { StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { AI_MODELS, DEFAULT_MODEL } from '../data/models';
import { AIModel } from '../types';
import { ModelSelector } from './model-selector';

interface ChatHeaderProps {
  onMenuPress: () => void;
  onNewChatPress: () => void;
  onSearchPress?: () => void;
  selectedModel?: AIModel;
  onModelChange?: (model: AIModel) => void;
}

export function ChatHeader({ 
  onMenuPress, 
  onNewChatPress, 
  onSearchPress,
  selectedModel = DEFAULT_MODEL,
  onModelChange,
}: ChatHeaderProps) {
  const [isModelSelectorVisible, setIsModelSelectorVisible] = useState(false);

  const handleModelSelect = (model: AIModel) => {
    onModelChange?.(model);
  };

  return (
    <View style={styles.header}>
      <TouchableOpacity 
        onPress={onMenuPress} 
        style={styles.menuButton} 
        activeOpacity={0.7}
      >
        <Ionicons name="menu" size={24} color={ChatTheme.textPrimary} />
      </TouchableOpacity>

      <TouchableOpacity 
        style={styles.modelSelector} 
        activeOpacity={0.7}
        onPress={() => setIsModelSelectorVisible(true)}
      >
        <Text style={styles.modelText}>{selectedModel.name}</Text>
        <Ionicons name="chevron-down" size={16} color={ChatTheme.textSecondary} />
      </TouchableOpacity>

      <ModelSelector
        visible={isModelSelectorVisible}
        selectedModel={selectedModel}
        models={AI_MODELS}
        onSelect={handleModelSelect}
        onClose={() => setIsModelSelectorVisible(false)}
      />

      <View style={styles.actions}>
        {onSearchPress && (
          <TouchableOpacity 
            style={styles.iconButton} 
            activeOpacity={0.7}
            onPress={onSearchPress}
          >
            <Ionicons name="search-outline" size={20} color={ChatTheme.textPrimary} />
          </TouchableOpacity>
        )}
        <TouchableOpacity 
          style={styles.iconButton} 
          onPress={onNewChatPress} 
          activeOpacity={0.7}
        >
          <Ionicons name="create-outline" size={20} color={ChatTheme.textPrimary} />
        </TouchableOpacity>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: ChatTheme.spacing.md,
    paddingVertical: ChatTheme.spacing.sm + 2,
    borderBottomWidth: 1,
    borderBottomColor: ChatTheme.border,
    backgroundColor: ChatTheme.background,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.1,
    shadowRadius: 3,
    elevation: 3,
  },
  menuButton: {
    padding: ChatTheme.spacing.xs,
  },
  modelSelector: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: ChatTheme.spacing.xs,
    paddingHorizontal: ChatTheme.spacing.sm + 2,
    paddingVertical: ChatTheme.spacing.xs,
  },
  modelText: {
    fontSize: ChatTheme.fontSize.md,
    color: ChatTheme.textPrimary,
    fontFamily: ChatTheme.fonts.mono,
  },
  actions: {
    flexDirection: 'row',
    gap: ChatTheme.spacing.xs,
  },
  iconButton: {
    padding: ChatTheme.spacing.xs,
  },
});
