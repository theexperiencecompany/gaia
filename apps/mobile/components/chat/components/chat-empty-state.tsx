/**
 * ChatEmptyState Component
 * Welcome screen with logo and suggestions
 */

import { ChatTheme } from '@/constants/chat-theme';
import React from 'react';
import { Image, ScrollView, StyleSheet, Text, View } from 'react-native';
import { Suggestion } from '../types';
import { SuggestionCard } from './suggestion-card';

interface ChatEmptyStateProps {
  suggestions: Suggestion[];
  onSuggestionPress: (text: string) => void;
}

export function ChatEmptyState({ suggestions, onSuggestionPress }: ChatEmptyStateProps) {
  return (
    <ScrollView 
      style={styles.container}
      contentContainerStyle={styles.content}
      showsVerticalScrollIndicator={false}
    >
      <View style={styles.welcomeSection}>
        <View style={styles.logoContainer}>
          <Image
            source={require('@/assets/logo/logo.svg')}
            style={styles.logo}
            resizeMode="contain"
          />
        </View>
        <Text style={styles.title}>Momentum compounds, web.</Text>
        <Text style={styles.subtitle}>Connect your tools to GAIA</Text>
      </View>

      <View style={styles.suggestionsSection}>
        <Text style={styles.suggestionsTitle}>Suggestions</Text>
        <View style={styles.suggestionGrid}>
          {suggestions.map((suggestion, index) => (
            <SuggestionCard
              key={suggestion.id}
              suggestion={suggestion}
              index={index}
              onPress={onSuggestionPress}
            />
          ))}
        </View>
      </View>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
  },
  content: {
    flexGrow: 1,
    paddingHorizontal: ChatTheme.spacing.lg,
    paddingTop: ChatTheme.spacing.xl * 2,
    paddingBottom: ChatTheme.spacing.xl,
  },
  welcomeSection: {
    alignItems: 'center',
    marginBottom: ChatTheme.spacing.xl * 2,
  },
  logoContainer: {
    marginBottom: ChatTheme.spacing.lg,
  },
  logo: {
    width: 56,
    height: 56,
  },
  title: {
    fontSize: 28,
    fontFamily: ChatTheme.fonts.semibold,
    color: ChatTheme.textPrimary,
    textAlign: 'center',
    marginBottom: ChatTheme.spacing.xs,
  },
  subtitle: {
    fontSize: ChatTheme.fontSize.md,
    color: ChatTheme.textSecondary,
    textAlign: 'center',
  },
  suggestionsSection: {
    width: '100%',
  },
  suggestionsTitle: {
    fontSize: ChatTheme.fontSize.md,
    fontFamily: ChatTheme.fonts.medium,
    color: ChatTheme.textSecondary,
    marginBottom: ChatTheme.spacing.md,
  },
  suggestionGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: ChatTheme.spacing.sm,
    justifyContent: 'space-between',
  },
});
