/**
 * ChatScreen Component
 * Main chat interface orchestrating all sub-components
 */

import { ChatTheme } from '@/shared/constants/chat-theme';
import React, { useEffect } from 'react';
import {
    FlatList,
    Keyboard,
    KeyboardAvoidingView,
    Platform,
    StyleSheet,
    Text,
    TouchableWithoutFeedback,
    View
} from 'react-native';
import { ChatInput } from './chat-input';
import { ChatMessage } from './chat-message';
import { ChatEmptyState } from './components/chat-empty-state';
import { ChatHeader } from './components/chat-header';
import { DEFAULT_SUGGESTIONS } from './data/suggestions';
import { useChat, useSidebar } from './hooks';
import { Sidebar } from './sidebar';
import { Message } from './types';

export function ChatScreen() {
  const {
    messages,
    isTyping,
    flatListRef,
    sendMessage,
    clearMessages,
    scrollToBottom,
  } = useChat();

  const {
    isSidebarOpen,
    closeSidebar,
    toggleSidebar,
  } = useSidebar();

  // Auto-scroll to bottom when new messages arrive
  useEffect(() => {
    scrollToBottom();
  }, [messages.length, scrollToBottom]);

  const handleSelectChat = (chatId: string) => {
    console.log('Selected chat:', chatId);
    closeSidebar();
  };

  const handleNewChat = () => {
    clearMessages();
    closeSidebar();
  };

  const renderMessage = ({ item }: { item: Message }) => (
    <ChatMessage message={item} />
  );

  const renderEmpty = () => (
    <ChatEmptyState
      suggestions={DEFAULT_SUGGESTIONS}
      onSuggestionPress={sendMessage}
    />
  );

  return (
    <KeyboardAvoidingView
      style={styles.container}
      behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
    >
      {/* Sidebar */}
      <Sidebar
        isOpen={isSidebarOpen}
        onClose={closeSidebar}
        onSelectChat={handleSelectChat}
        onNewChat={handleNewChat}
      />

      {/* Header */}
      <ChatHeader
        onMenuPress={toggleSidebar}
        onNewChatPress={handleNewChat}
        onSearchPress={() => console.log('Search pressed')}
      />

      {/* Messages List */}
      <TouchableWithoutFeedback onPress={Keyboard.dismiss}>
        <View style={styles.messagesContainer}>
          <FlatList
            ref={flatListRef}
            data={messages}
            renderItem={renderMessage}
            keyExtractor={item => item.id}
            contentContainerStyle={styles.messagesList}
            ListEmptyComponent={renderEmpty}
            showsVerticalScrollIndicator={false}
            keyboardShouldPersistTaps="handled"
          />
        </View>
      </TouchableWithoutFeedback>

      {/* Typing Indicator */}
      {isTyping && (
        <View style={styles.typingContainer}>
          <Text style={styles.typingText}>GAIA is typing...</Text>
        </View>
      )}

      {/* Input */}
      <ChatInput onSend={sendMessage} />
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: ChatTheme.background,
  },
  messagesContainer: {
    flex: 1,
  },
  messagesList: {
    paddingVertical: ChatTheme.spacing.md,
    flexGrow: 1,
  },
  typingContainer: {
    paddingHorizontal: ChatTheme.spacing.md + 8,
    paddingBottom: ChatTheme.spacing.xs,
  },
  typingText: {
    fontSize: ChatTheme.fontSize.sm,
    color: ChatTheme.textSecondary,
    fontStyle: 'italic',
  },
});
