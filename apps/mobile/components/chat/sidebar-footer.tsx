/**
 * SidebarFooter Component
 * User info and support section for sidebar
 */

import { ChatTheme } from '@/constants/chat-theme';
import { Ionicons } from '@expo/vector-icons';
import React from 'react';
import { StyleSheet, Text, TouchableOpacity, View } from 'react-native';

export function SidebarFooter() {
  return (
    <View style={styles.container}>
      {/* Need Support */}
      <TouchableOpacity style={styles.supportButton}>
        <Ionicons name="help-circle-outline" size={20} color={ChatTheme.textSecondary} />
        <Text style={styles.supportText}>Need Support?</Text>
      </TouchableOpacity>

      {/* User Info */}
      <TouchableOpacity style={styles.userInfo}>
        <View style={styles.avatar}>
          <Text style={styles.avatarText}>W</Text>
        </View>
        <View style={styles.userDetails}>
          <Text style={styles.userName}>web test</Text>
          <Text style={styles.userPlan}>GAIA Free</Text>
        </View>
        <Ionicons name="chevron-down" size={20} color={ChatTheme.textSecondary} />
      </TouchableOpacity>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    borderTopWidth: 1,
    borderTopColor: ChatTheme.border,
    paddingVertical: ChatTheme.spacing.sm,
  },
  supportButton: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: ChatTheme.spacing.md,
    paddingVertical: ChatTheme.spacing.sm + 2,
    gap: ChatTheme.spacing.sm,
  },
  supportText: {
    color: ChatTheme.textPrimary,
    fontSize: ChatTheme.fontSize.md,
    fontFamily: ChatTheme.fonts.regular,
  },
  userInfo: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: ChatTheme.spacing.md,
    paddingVertical: ChatTheme.spacing.sm,
    gap: ChatTheme.spacing.sm,
  },
  avatar: {
    width: 32,
    height: 32,
    borderRadius: 16,
    backgroundColor: '#00aa88',
    justifyContent: 'center',
    alignItems: 'center',
  },
  avatarText: {
    color: ChatTheme.textPrimary,
    fontSize: ChatTheme.fontSize.md,
    fontWeight: 'bold',
  },
  userDetails: {
    flex: 1,
  },
  userName: {
    color: ChatTheme.textPrimary,
    fontSize: ChatTheme.fontSize.md,
    fontWeight: '500',
    fontFamily: ChatTheme.fonts.medium,
  },
  userPlan: {
    color: ChatTheme.textSecondary,
    fontSize: ChatTheme.fontSize.sm,
    fontFamily: ChatTheme.fonts.regular,
  },
});
