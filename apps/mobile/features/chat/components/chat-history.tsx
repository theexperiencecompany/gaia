/**
 * Chat History Component
 * Displays list of past chat sessions grouped by time
 */

import { ChatTheme } from '@/shared/constants/chat-theme';
import { Ionicons } from '@expo/vector-icons';
import React, { useState } from 'react';
import { ScrollView, StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { useChatContext } from '../hooks/use-chat-context';

interface ChatHistoryItem {
  id: string;
  title: string;
  timestamp: Date;
  isStarred?: boolean;
}

interface ChatHistoryProps {
  onSelectChat: (chatId: string) => void;
  onNewChat: () => void;
}

interface CategorySectionProps {
  title: string;
  items: ChatHistoryItem[];
  isExpanded: boolean;
  onToggle: () => void;
  onSelectChat: (chatId: string) => void;
  activeChatId: string | null;
}

// Mock data - replace with actual chat history
const starredChats: ChatHistoryItem[] = [
  { id: 's1', title: 'this is random chat', timestamp: new Date(), isStarred: true },
];

const todayChats: ChatHistoryItem[] = [
  { id: 't1', title: 'Greeting message', timestamp: new Date() },
];

const yesterdayChats: ChatHistoryItem[] = [
  { id: 'y1', title: 'Greeting message', timestamp: new Date() },
];

const allTimeChats: ChatHistoryItem[] = [
  { id: 'a1', title: 'Casual greeting', timestamp: new Date() },
  { id: 'a2', title: 'hello message text', timestamp: new Date() },
  { id: 'a3', title: 'hello message example', timestamp: new Date() },
  { id: 'a4', title: 'General greeting', timestamp: new Date() },
  { id: 'a5', title: 'General greeting message re', timestamp: new Date() },
  { id: 'a6', title: 'this is random chat', timestamp: new Date() },
];

function CategorySection({ title, items, isExpanded, onToggle, onSelectChat, activeChatId }: CategorySectionProps) {
  return (
    <View style={styles.categorySection}>
      <TouchableOpacity style={styles.categoryHeader} onPress={onToggle}>
        <Text style={styles.categoryTitle}>{title}</Text>
        <Ionicons 
          name={isExpanded ? "chevron-up" : "chevron-down"} 
          size={16} 
          color={ChatTheme.textSecondary} 
        />
      </TouchableOpacity>
      
      {isExpanded && items.map((item) => {
        const isActive = item.id === activeChatId;
        return (
          <TouchableOpacity
            key={item.id}
            style={[styles.historyItem, isActive && styles.historyItemActive]}
            onPress={() => onSelectChat(item.id)}
          >
            <Ionicons 
              name={item.isStarred ? "star" : "chatbubble-outline"} 
              size={16} 
              color={isActive ? ChatTheme.accent : ChatTheme.textSecondary} 
            />
            <Text style={[styles.historyItemText, isActive && styles.historyItemTextActive]} numberOfLines={1}>
              {item.title}
            </Text>
          </TouchableOpacity>
        );
      })}
    </View>
  );
}

export function ChatHistory({ onSelectChat, onNewChat }: ChatHistoryProps) {
  const { activeChatId } = useChatContext();
  const [expandedSections, setExpandedSections] = useState({
    starred: true,
    today: true,
    yesterday: true,
    allTime: true,
  });

  const toggleSection = (section: keyof typeof expandedSections) => {
    setExpandedSections(prev => ({ ...prev, [section]: !prev[section] }));
  };

  return (
    <ScrollView style={styles.container} showsVerticalScrollIndicator={false}>
      {/* New Chat Button */}
      <TouchableOpacity style={styles.newChatButton} onPress={onNewChat}>
        <Ionicons name="add" size={18} color={ChatTheme.background} />
        <Text style={styles.newChatText}>New Chat</Text>
      </TouchableOpacity>

      {/* Starred Chats */}
      {starredChats.length > 0 && (
        <CategorySection
          title="Starred Chats"
          items={starredChats}
          isExpanded={expandedSections.starred}
          onToggle={() => toggleSection('starred')}
          onSelectChat={onSelectChat}
          activeChatId={activeChatId}
        />
      )}

      {/* Today */}
      {todayChats.length > 0 && (
        <CategorySection
          title="Today"
          items={todayChats}
          isExpanded={expandedSections.today}
          onToggle={() => toggleSection('today')}
          onSelectChat={onSelectChat}
          activeChatId={activeChatId}
        />
      )}

      {/* Yesterday */}
      {yesterdayChats.length > 0 && (
        <CategorySection
          title="Yesterday"
          items={yesterdayChats}
          isExpanded={expandedSections.yesterday}
          onToggle={() => toggleSection('yesterday')}
          onSelectChat={onSelectChat}
          activeChatId={activeChatId}
        />
      )}

      {/* All Time */}
      {allTimeChats.length > 0 && (
        <CategorySection
          title="All time"
          items={allTimeChats}
          isExpanded={expandedSections.allTime}
          onToggle={() => toggleSection('allTime')}
          onSelectChat={onSelectChat}
          activeChatId={activeChatId}
        />
      )}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
  },
  newChatButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    padding: ChatTheme.spacing.sm + 2,
    marginHorizontal: ChatTheme.spacing.md,
    marginTop: ChatTheme.spacing.md,
    marginBottom: ChatTheme.spacing.md,
    backgroundColor: ChatTheme.accent,
    borderRadius: ChatTheme.borderRadius.md,
    shadowColor: '#000000',
    shadowOffset: {
      width: -6,
      height: -6,
    },
    shadowOpacity: 0.5,
    shadowRadius: 8,
    elevation: 10,
  },
  newChatText: {
    color: ChatTheme.background,
    fontSize: ChatTheme.fontSize.md,
    marginLeft: ChatTheme.spacing.sm,
    fontWeight: '600',
    fontFamily: ChatTheme.fonts.semibold,
  },
  categorySection: {
    marginBottom: ChatTheme.spacing.sm,
  },
  categoryHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: ChatTheme.spacing.md,
    paddingVertical: ChatTheme.spacing.sm,
  },
  categoryTitle: {
    color: ChatTheme.textSecondary,
    fontSize: ChatTheme.fontSize.sm,
    fontWeight: '500',
    fontFamily: ChatTheme.fonts.medium,
  },
  historyItem: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: ChatTheme.spacing.md,
    paddingVertical: ChatTheme.spacing.sm,
    gap: ChatTheme.spacing.sm,
  },
  historyItemActive: {
    backgroundColor: ChatTheme.messageBackground,
    borderLeftWidth: 3,
    borderLeftColor: ChatTheme.accent,
  },
  historyItemText: {
    flex: 1,
    color: ChatTheme.textPrimary,
    fontSize: ChatTheme.fontSize.md,
    fontFamily: ChatTheme.fonts.regular,
  },
  historyItemTextActive: {
    color: ChatTheme.accent,
    fontWeight: '600',
    fontFamily: ChatTheme.fonts.semibold,
  },
});
