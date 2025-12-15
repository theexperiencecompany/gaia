import { ChatScreen } from '@/features/chat/chat-screen';
import { ChatProvider } from '@/features/chat/hooks/use-chat-context';
import { ChatTheme } from '@/shared/constants/chat-theme';
import React from 'react';
import { StyleSheet } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

export default function App() {
  return (
    <ChatProvider>
      <SafeAreaView style={styles.container}>
        <ChatScreen />
      </SafeAreaView>
    </ChatProvider>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: ChatTheme.background,
  },
});
