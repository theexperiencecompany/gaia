/**
 * Sidebar Footer Component
 * User info and support section for sidebar
 */

import { Ionicons } from "@expo/vector-icons";
import {
  ActivityIndicator,
  Image,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from "react-native";
import { useAuth } from "@/features/auth";
import { ChatTheme } from "@/shared/constants/chat-theme";

export function SidebarFooter() {
  const { user, isLoading, signOut } = useAuth();

  const handleUserPress = () => {
    // TODO: Open user menu with more options
    signOut();
  };

  // Get user initials for avatar fallback
  const getInitials = (name?: string) => {
    if (!name) return "U";
    const parts = name.trim().split(" ");
    if (parts.length >= 2) {
      return `${parts[0][0]}${parts[parts.length - 1][0]}`.toUpperCase();
    }
    return name[0].toUpperCase();
  };

  // Generate avatar color based on email
  const getAvatarColor = (email?: string) => {
    if (!email) return "#00aa88";
    const colors = [
      "#00aa88",
      "#0088cc",
      "#8855cc",
      "#cc5588",
      "#cc8855",
      "#55cc88",
    ];
    const hash = email
      .split("")
      .reduce((acc, char) => acc + char.charCodeAt(0), 0);
    return colors[hash % colors.length];
  };

  if (isLoading) {
    return (
      <View style={styles.container}>
        <View style={styles.loadingContainer}>
          <ActivityIndicator size="small" color={ChatTheme.accent} />
        </View>
      </View>
    );
  }

  return (
    <View style={styles.container}>
      {/* Need Support */}
      <TouchableOpacity style={styles.supportButton}>
        <Ionicons
          name="help-circle-outline"
          size={20}
          color={ChatTheme.textSecondary}
        />
        <Text style={styles.supportText}>Need Support?</Text>
      </TouchableOpacity>

      {/* User Info */}
      <TouchableOpacity style={styles.userInfo} onPress={handleUserPress}>
        {user?.picture ? (
          <Image source={{ uri: user.picture }} style={styles.avatarImage} />
        ) : (
          <View
            style={[
              styles.avatar,
              { backgroundColor: getAvatarColor(user?.email) },
            ]}
          >
            <Text style={styles.avatarText}>{getInitials(user?.name)}</Text>
          </View>
        )}
        <View style={styles.userDetails}>
          <Text style={styles.userName} numberOfLines={1}>
            {user?.name || "User"}
          </Text>
          <Text style={styles.userPlan}>GAIA Free</Text>
        </View>
        <Ionicons
          name="chevron-down"
          size={20}
          color={ChatTheme.textSecondary}
        />
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
  loadingContainer: {
    paddingVertical: ChatTheme.spacing.lg,
    alignItems: "center",
    justifyContent: "center",
  },
  supportButton: {
    flexDirection: "row",
    alignItems: "center",
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
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: ChatTheme.spacing.md,
    paddingVertical: ChatTheme.spacing.sm,
    gap: ChatTheme.spacing.sm,
  },
  avatar: {
    width: 32,
    height: 32,
    borderRadius: 16,
    justifyContent: "center",
    alignItems: "center",
  },
  avatarImage: {
    width: 32,
    height: 32,
    borderRadius: 16,
  },
  avatarText: {
    color: ChatTheme.textPrimary,
    fontSize: ChatTheme.fontSize.md,
    fontWeight: "bold",
  },
  userDetails: {
    flex: 1,
  },
  userName: {
    color: ChatTheme.textPrimary,
    fontSize: ChatTheme.fontSize.md,
    fontWeight: "500",
    fontFamily: ChatTheme.fonts.medium,
  },
  userPlan: {
    color: ChatTheme.textSecondary,
    fontSize: ChatTheme.fontSize.sm,
    fontFamily: ChatTheme.fonts.regular,
  },
});
