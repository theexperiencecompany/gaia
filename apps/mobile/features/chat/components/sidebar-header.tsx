/**
 * SidebarHeader Component
 * Logo and menu toggle for sidebar
 */

import { Ionicons } from "@expo/vector-icons";
import { Image, StyleSheet, Text, TouchableOpacity, View } from "react-native";
import { ChatTheme } from "@/shared/constants/chat-theme";

interface SidebarHeaderProps {
  onClose: () => void;
}

export function SidebarHeader({ onClose }: SidebarHeaderProps) {
  return (
    <View style={styles.container}>
      <View style={styles.logoContainer}>
        <Image
          source={require("@/assets/logo/logo.webp")}
          style={styles.logo}
          resizeMode="contain"
        />
        <Text style={styles.logoText}>GAIA</Text>
      </View>
      <TouchableOpacity onPress={onClose} style={styles.closeButton}>
        <Ionicons name="chevron-back" size={24} color={ChatTheme.textPrimary} />
      </TouchableOpacity>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: ChatTheme.spacing.md,
    paddingVertical: ChatTheme.spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: ChatTheme.border,
  },
  logoContainer: {
    flexDirection: "row",
    alignItems: "center",
    gap: ChatTheme.spacing.sm,
  },
  logo: {
    width: 32,
    height: 32,
  },
  logoText: {
    fontSize: 18,
    fontWeight: "bold",
    color: ChatTheme.textPrimary,
    letterSpacing: 1,
    fontFamily: ChatTheme.fonts.bold,
  },
  closeButton: {
    padding: ChatTheme.spacing.xs,
  },
});
