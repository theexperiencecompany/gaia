import { ChatScreen } from '@/features/chat/chat-screen';
import { ChatTheme } from '@/shared/constants/chat-theme';
import React from 'react';
import { SafeAreaView, StyleSheet } from 'react-native';

export default function App() {
  return (
    <SafeAreaView style={styles.container}>
      <ChatScreen />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: ChatTheme.background,
  },
});
