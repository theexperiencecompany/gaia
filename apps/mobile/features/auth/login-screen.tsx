/**
 * LoginScreen Component
 * Login screen with SSO and Google authentication
 */

import { ChatTheme } from '@/shared/constants/chat-theme';
import { Ionicons } from '@expo/vector-icons';
import React, { useState } from 'react';
import {
  Image,
  KeyboardAvoidingView,
  Platform,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

interface LoginScreenProps {
  onLogin: () => void;
  onSignUp: () => void;
}

export function LoginScreen({ onLogin, onSignUp }: LoginScreenProps) {
  const [email, setEmail] = useState('');

  const handleSSOLogin = () => {
    console.log('SSO Login with:', email);
    // TODO: Implement SSO login
    onLogin();
  };

  const handleGoogleLogin = () => {
    console.log('Google Login');
    // TODO: Implement Google login
    onLogin();
  };

  const handleSignUp = () => {
    console.log('Navigate to Sign Up');
    onSignUp();
  };

  return (
    <View style={styles.container}>
      {/* Full Background Image */}
      <Image 
        source={require('@/assets/background/login.webp')} 
        style={styles.backgroundImage}
        resizeMode="cover"
        blurRadius={0.5}
        fadeDuration={300}
      />
      
      {/* Dark Overlay */}
      <View style={styles.overlay} />
      
      <SafeAreaView style={styles.safeArea}>
        <KeyboardAvoidingView
          style={styles.keyboardView}
          behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
        >
          {/* Login Card */}
          <View style={styles.card}>
            {/* Logo and Title */}
            <View style={styles.header}>
              <View style={styles.logoContainer}>
                <Image 
                  source={require('@/assets/logo/logo.webp')} 
                  style={styles.logo}
                  resizeMode="contain"
                />
              </View>
              <Text style={styles.title}>Let's Get You Back In</Text>
            </View>

        {/* Login Form */}
        <View style={styles.form}>
          {/* Email Input */}
          <View style={styles.inputContainer}>
            <Text style={styles.label}>Email</Text>
            <TextInput
              style={styles.input}
              placeholder="Your email address"
              placeholderTextColor={ChatTheme.textSecondary}
              value={email}
              onChangeText={setEmail}
              keyboardType="email-address"
              autoCapitalize="none"
              autoCorrect={false}
            />
          </View>

          {/* SSO Button */}
          <TouchableOpacity
            style={styles.ssoButton}
            onPress={handleSSOLogin}
            activeOpacity={0.8}
          >
            <Text style={styles.ssoButtonText}>Continue with SSO</Text>
          </TouchableOpacity>

          {/* Divider */}
          <View style={styles.divider}>
            <View style={styles.dividerLine} />
            <Text style={styles.dividerText}>OR</Text>
            <View style={styles.dividerLine} />
          </View>

          {/* Google Button */}
          <TouchableOpacity
            style={styles.googleButton}
            onPress={handleGoogleLogin}
            activeOpacity={0.8}
          >
            <Image 
              source={require('@/assets/icons/google-logo.png')}
              style={styles.googleIcon}
              resizeMode="contain"
            />
            <Text style={styles.googleButtonText}>Continue with Google</Text>
          </TouchableOpacity>

          {/* Sign Up Link */}
          <View style={styles.signUpContainer}>
            <Text style={styles.signUpText}>Don't have an account? </Text>
            <TouchableOpacity onPress={handleSignUp}>
              <Text style={styles.signUpLink}>Sign up</Text>
            </TouchableOpacity>
          </View>
        </View>

            {/* Footer */}
            <View style={styles.footer}>
              <TouchableOpacity>
                <Text style={styles.footerLink}>Terms of Service</Text>
              </TouchableOpacity>
              <Text style={styles.footerText}> and </Text>
              <TouchableOpacity>
                <Text style={styles.footerLink}>Privacy Policy</Text>
              </TouchableOpacity>
            </View>
          </View>
        </KeyboardAvoidingView>
      </SafeAreaView>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#0a1929',
  },
  backgroundImage: {
    position: 'absolute',
    width: '100%',
    height: '100%',
  },
  overlay: {
    position: 'absolute',
    width: '100%',
    height: '100%',
    backgroundColor: 'rgba(0, 0, 0, 0.5)',
  },
  safeArea: {
    flex: 1,
  },
  keyboardView: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    paddingHorizontal: ChatTheme.spacing.lg,
  },
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
  form: {
    width: '100%',
  },
  inputContainer: {
    marginBottom: ChatTheme.spacing.md,
  },
  label: {
    fontSize: ChatTheme.fontSize.md,
    color: ChatTheme.textPrimary,
    marginBottom: ChatTheme.spacing.sm,
    fontFamily: ChatTheme.fonts.medium,
  },
  input: {
    backgroundColor: 'rgba(39, 39, 42, 0.8)',
    borderRadius: ChatTheme.borderRadius.md,
    paddingHorizontal: ChatTheme.spacing.md,
    paddingVertical: 14,
    fontSize: ChatTheme.fontSize.md,
    color: ChatTheme.textPrimary,
    fontFamily: ChatTheme.fonts.regular,
    borderWidth: 1,
    borderColor: 'rgba(255, 255, 255, 0.1)',
  },
  ssoButton: {
    backgroundColor: ChatTheme.accent,
    borderRadius: ChatTheme.borderRadius.md,
    paddingVertical: 14,
    alignItems: 'center',
    marginBottom: ChatTheme.spacing.md,
    shadowColor: ChatTheme.accent,
    shadowOffset: {
      width: 0,
      height: 4,
    },
    shadowOpacity: 0.4,
    shadowRadius: 10,
    elevation: 8,
  },
  ssoButtonText: {
    fontSize: ChatTheme.fontSize.md,
    fontWeight: '600',
    color: '#000000',
    fontFamily: ChatTheme.fonts.semibold,
  },
  divider: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: ChatTheme.spacing.md,
  },
  dividerLine: {
    flex: 1,
    height: 1,
    backgroundColor: 'rgba(255, 255, 255, 0.15)',
  },
  dividerText: {
    marginHorizontal: ChatTheme.spacing.md,
    fontSize: ChatTheme.fontSize.sm,
    color: ChatTheme.textSecondary,
    fontFamily: ChatTheme.fonts.medium,
  },
  googleButton: {
    backgroundColor: 'rgba(39, 39, 42, 0.8)',
    borderRadius: ChatTheme.borderRadius.md,
    paddingVertical: 14,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: ChatTheme.spacing.sm,
    borderWidth: 1,
    borderColor: 'rgba(255, 255, 255, 0.2)',
  },
  googleIcon: {
    width: 18,
    height: 18,
  },
  googleButtonText: {
    fontSize: ChatTheme.fontSize.md,
    fontWeight: '500',
    color: ChatTheme.textPrimary,
    fontFamily: ChatTheme.fonts.medium,
  },
  signUpContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    marginTop: ChatTheme.spacing.md,
  },
  signUpText: {
    fontSize: ChatTheme.fontSize.md,
    color: ChatTheme.textSecondary,
    fontFamily: ChatTheme.fonts.regular,
  },
  signUpLink: {
    fontSize: ChatTheme.fontSize.md,
    color: ChatTheme.accent,
    fontFamily: ChatTheme.fonts.semibold,
    fontWeight: '600',
  },
  footer: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    marginTop: ChatTheme.spacing.lg,
    flexWrap: 'wrap',
  },
  footerText: {
    fontSize: ChatTheme.fontSize.sm,
    color: ChatTheme.textSecondary,
    fontFamily: ChatTheme.fonts.regular,
  },
  footerLink: {
    fontSize: ChatTheme.fontSize.sm,
    color: ChatTheme.textSecondary,
    fontFamily: ChatTheme.fonts.regular,
    textDecorationLine: 'underline',
  },
});
