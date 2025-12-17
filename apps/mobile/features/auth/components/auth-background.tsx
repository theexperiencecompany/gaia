/**
 * Auth Background Component
 * Reusable background with image and overlay for auth screens
 */

import React from 'react';
import { Image, StyleSheet, View, ImageSourcePropType } from 'react-native';

interface AuthBackgroundProps {
  source: ImageSourcePropType;
  overlayOpacity?: number;
}

export function AuthBackground({ source, overlayOpacity = 0.5 }: AuthBackgroundProps) {
  return (
    <>
      <Image 
        source={source} 
        style={styles.backgroundImage}
        resizeMode="cover"
        blurRadius={0.5}
        fadeDuration={300}
      />
      <View style={[styles.overlay, { backgroundColor: `rgba(0, 0, 0, ${overlayOpacity})` }]} />
    </>
  );
}

const styles = StyleSheet.create({
  backgroundImage: {
    position: 'absolute',
    width: '100%',
    height: '100%',
  },
  overlay: {
    position: 'absolute',
    width: '100%',
    height: '100%',
  },
});
