/**
 * Auth Footer Component
 * Reusable footer with legal links for auth screens
 */

import { ChatTheme } from '@/shared/constants/chat-theme';
import React from 'react';
import { StyleSheet, Text, TouchableOpacity, View } from 'react-native';

interface AuthFooterProps {
  showSignUpDisclaimer?: boolean;
}

export function AuthFooter({ showSignUpDisclaimer = false }: AuthFooterProps) {
  const handleTermsPress = () => {
    console.log('Navigate to Terms of Service');
    // TODO: Implement navigation
  };

  const handlePrivacyPress = () => {
    console.log('Navigate to Privacy Policy');
    // TODO: Implement navigation
  };

  return (
    <View style={styles.footer}>
      {showSignUpDisclaimer && (
        <Text style={styles.footerText}>By creating an account, you agree to the </Text>
      )}
      <View style={styles.footerLinks}>
        <TouchableOpacity onPress={handleTermsPress}>
          <Text style={styles.footerLink}>Terms of Service</Text>
        </TouchableOpacity>
        <Text style={styles.footerText}> and </Text>
        <TouchableOpacity onPress={handlePrivacyPress}>
          <Text style={styles.footerLink}>Privacy Policy</Text>
        </TouchableOpacity>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  footer: {
    alignItems: 'center',
    justifyContent: 'center',
    marginTop: ChatTheme.spacing.lg,
  },
  footerLinks: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    justifyContent: 'center',
  },
  footerText: {
    fontSize: ChatTheme.fontSize.sm,
    color: ChatTheme.textSecondary,
    fontFamily: ChatTheme.fonts.regular,
    textAlign: 'center',
  },
  footerLink: {
    fontSize: ChatTheme.fontSize.sm,
    color: ChatTheme.textSecondary,
    fontFamily: ChatTheme.fonts.regular,
    textDecorationLine: 'underline',
  },
});
