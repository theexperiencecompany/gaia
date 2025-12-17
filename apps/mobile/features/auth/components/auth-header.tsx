/**
 * Auth Header Component
 * Reusable header with logo and title for auth screens
 */

import { ChatTheme } from '@/shared/constants/chat-theme';
import React from 'react';
import { Image, StyleSheet, Text, View } from 'react-native';

interface AuthHeaderProps {
  title: string;
}

export function AuthHeader({ title }: AuthHeaderProps) {
  return (
    <View style={styles.header}>
      <View style={styles.logoContainer}>
        <Image 
          source={require('@/assets/logo/logo.webp')} 
          style={styles.logo}
          resizeMode="contain"
        />
      </View>
      <Text style={styles.title}>{title}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  header: {
    alignItems: 'center',
    marginBottom: ChatTheme.spacing.xl,
  },
  logoContainer: {
    width: 70,
    height: 70,
    borderRadius: 35,
    backgroundColor: 'rgba(22, 193, 255, 0.15)',
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: ChatTheme.spacing.md,
  },
  logo: {
    width: 50,
    height: 50,
  },
  title: {
    fontSize: 24,
    fontWeight: '700',
    color: ChatTheme.textPrimary,
    fontFamily: ChatTheme.fonts.bold,
    textAlign: 'center',
  },
});
