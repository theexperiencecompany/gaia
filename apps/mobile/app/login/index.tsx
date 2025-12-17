/**
 * Login Screen - app/login/index.tsx
 * Handles user authentication with WorkOS SSO
 * Following Expo Router conventions - separate route for login
 */

import { ChatTheme } from '@/shared/constants/chat-theme';
import { startOAuthFlow, fetchUserInfo } from '@/shared/services/auth-service';
import { storeAuthToken, storeUserInfo } from '@/shared/utils/auth-storage';
import { useAuth } from '@/features/auth';
import { useRouter } from 'expo-router';
import React, { useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  Image,
  KeyboardAvoidingView,
  Platform,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

export default function LoginScreen() {
  const router = useRouter();
  const { refreshAuth } = useAuth();
  const [isLoading, setIsLoading] = useState(false);

  const handleLogin = async () => {
    setIsLoading(true);
    
    try {
      // Start OAuth flow and get token
      const token = await startOAuthFlow();
      
      // Store the authentication token
      await storeAuthToken(token);
      
      // Fetch and store user information
      const userInfo = await fetchUserInfo(token);
      await storeUserInfo(userInfo);
      
      // Refresh auth state to trigger navigation
      await refreshAuth();
      
      // Navigate to main app
      router.replace('/(tabs)');
    } catch (error) {
      console.error('Login error:', error);
      Alert.alert(
        'Login Failed',
        error instanceof Error ? error.message : 'An unexpected error occurred. Please try again.',
        [{ text: 'OK' }]
      );
    } finally {
      setIsLoading(false);
    }
  };

  const handleSignUp = () => {
    router.push('/signup');
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
              <Text style={styles.title}>Let&apos;s Get You Back In</Text>
            </View>

            {/* Login Form */}
            <View style={styles.form}>
              {/* Login Button */}
              <TouchableOpacity
                style={[styles.loginButton, isLoading && styles.loginButtonDisabled]}
                onPress={handleLogin}
                activeOpacity={0.8}
                disabled={isLoading}
              >
                {isLoading ? (
                  <ActivityIndicator color="#000000" />
                ) : (
                  <Text style={styles.loginButtonText}>Continue with WorkOS</Text>
                )}
              </TouchableOpacity>

              {/* Sign Up Link */}
              <View style={styles.signUpContainer}>
                <Text style={styles.signUpText}>Don&apos;t have an account? </Text>
                <TouchableOpacity onPress={handleSignUp} disabled={isLoading}>
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
  loginButton: {
    backgroundColor: ChatTheme.accent,
    borderRadius: ChatTheme.borderRadius.md,
    paddingVertical: 14,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: ChatTheme.spacing.md,
    shadowColor: ChatTheme.accent,
    shadowOffset: {
      width: 0,
      height: 4,
    },
    shadowOpacity: 0.4,
    shadowRadius: 10,
    elevation: 8,
    minHeight: 48,
  },
  loginButtonDisabled: {
    opacity: 0.6,
  },
  loginButtonText: {
    fontSize: ChatTheme.fontSize.md,
    fontWeight: '600',
    color: '#000000',
    fontFamily: ChatTheme.fonts.semibold,
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
