/**
 * Auth Card Component
 * Reusable card container for auth screens
 */

import { ChatTheme } from '@/shared/constants/chat-theme';
import React, { ReactNode } from 'react';
import { StyleSheet, View } from 'react-native';

interface AuthCardProps {
  children: ReactNode;
}

export function AuthCard({ children }: AuthCardProps) {
  return <View style={styles.card}>{children}</View>;
}

const styles = StyleSheet.create({
  card: {
    width: '100%',
    maxWidth: 450,
    backgroundColor: 'rgba(26, 26, 26, 0.95)',
    borderRadius: ChatTheme.borderRadius.lg + 4,
    paddingHorizontal: ChatTheme.spacing.xl,
    paddingVertical: ChatTheme.spacing.xl + 8,
    borderWidth: 1,
    borderColor: 'rgba(255, 255, 255, 0.1)',
    shadowColor: '#000',
    shadowOffset: {
      width: 0,
      height: 10,
    },
    shadowOpacity: 0.5,
    shadowRadius: 20,
    elevation: 20,
  },
});
