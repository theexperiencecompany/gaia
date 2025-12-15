/**
 * SignUpScreen Component
 * Sign up screen with Google authentication
 */

import { ChatTheme } from '@/shared/constants/chat-theme';
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

interface SignUpScreenProps {
  onSignUp: () => void;
  onSignIn: () => void;
}

export function SignUpScreen({ onSignUp, onSignIn }: SignUpScreenProps) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');

  const handleGoogleSignUp = () => {
    console.log('Google Sign Up');
    // TODO: Implement Google sign up
    onSignUp();
  };

  const handleEmailSignUp = () => {
    console.log('Email Sign Up with:', email);
    // TODO: Implement email sign up
    if (password !== confirmPassword) {
      console.error('Passwords do not match');
      return;
    }
    onSignUp();
  };

  return (
    <View style={styles.container}>
      {/* Full Background Image */}
      <Image 
        source={require('@/assets/background/signup.webp')} 
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
          {/* Sign Up Card */}
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
              <Text style={styles.title}>Time to Supercharge You.</Text>
            </View>

            {/* Sign Up Form */}
            <View style={styles.form}>
              {/* Google Button */}
              <TouchableOpacity
                style={styles.googleButton}
                onPress={handleGoogleSignUp}
                activeOpacity={0.8}
              >
                <Image 
                  source={require('@/assets/icons/google-logo.png')}
                  style={styles.googleIcon}
                  resizeMode="contain"
                />
                <Text style={styles.googleButtonText}>Continue with Google</Text>
              </TouchableOpacity>

              {/* Sign In Link */}
              <View style={styles.signInContainer}>
                <Text style={styles.signInText}>Already have an account? </Text>
                <TouchableOpacity onPress={onSignIn}>
                  <Text style={styles.signInLink}>Sign in</Text>
                </TouchableOpacity>
              </View>
            </View>

            {/* Footer */}
            <View style={styles.footer}>
              <Text style={styles.footerText}>By creating an account, you agree to the </Text>
              <View style={styles.footerLinks}>
                <TouchableOpacity>
                  <Text style={styles.footerLink}>Terms of Service</Text>
                </TouchableOpacity>
                <Text style={styles.footerText}> and </Text>
                <TouchableOpacity>
                  <Text style={styles.footerLink}>Privacy Policy</Text>
                </TouchableOpacity>
              </View>
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
    backgroundColor: '#0c1f3d',
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
  signUpButton: {
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
  signUpButtonText: {
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
  signInContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    marginTop: ChatTheme.spacing.md,
  },
  signInText: {
    fontSize: ChatTheme.fontSize.md,
    color: ChatTheme.textSecondary,
    fontFamily: ChatTheme.fonts.regular,
  },
  signInLink: {
    fontSize: ChatTheme.fontSize.md,
    color: ChatTheme.accent,
    fontFamily: ChatTheme.fonts.semibold,
    fontWeight: '600',
  },
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
