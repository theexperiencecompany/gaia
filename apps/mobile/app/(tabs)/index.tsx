import { LoginScreen, SignUpScreen } from '@/features/auth';
import { ChatScreen } from '@/features/chat/chat-screen';
import { ChatProvider } from '@/features/chat/hooks/use-chat-context';
import { ChatTheme } from '@/shared/constants/chat-theme';
import React, { useState } from 'react';
import { StyleSheet } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

export default function App() {
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [showSignUp, setShowSignUp] = useState(false);

  const handleLogin = () => {
    setIsAuthenticated(true);
  };

  const handleSignUp = () => {
    setIsAuthenticated(true);
  };

  const toggleAuthScreen = () => {
    setShowSignUp(!showSignUp);
  };

  if (!isAuthenticated) {
    if (showSignUp) {
      return <SignUpScreen onSignUp={handleSignUp} onSignIn={toggleAuthScreen} />;
    }
    return <LoginScreen onLogin={handleLogin} onSignUp={toggleAuthScreen} />;
  }

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
