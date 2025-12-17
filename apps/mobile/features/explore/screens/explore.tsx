/**
 * Explore Screen
 * Discovery and exploration interface for users
 */

import { Ionicons } from "@expo/vector-icons";
import {
  ScrollView,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from "react-native";
import { ChatTheme } from "@/shared/constants/chat-theme";

export function ExploreScreen() {
  const exploreCategories = [
    { id: "1", title: "Trending Topics", icon: "trending-up" as const },
    { id: "2", title: "Recent Updates", icon: "time" as const },
    { id: "3", title: "Popular Queries", icon: "flame" as const },
    { id: "4", title: "Saved Items", icon: "bookmark" as const },
  ];

  return (
    <View style={styles.container}>
      {/* Header */}
      <View style={styles.header}>
        <Text style={styles.headerTitle}>Explore</Text>
        <TouchableOpacity>
          <Ionicons
            name="settings-outline"
            size={24}
            color={ChatTheme.textPrimary}
          />
        </TouchableOpacity>
      </View>

      {/* Content */}
      <ScrollView style={styles.content} showsVerticalScrollIndicator={false}>
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Categories</Text>
          {exploreCategories.map((category) => (
            <TouchableOpacity key={category.id} style={styles.categoryCard}>
              <View style={styles.categoryIcon}>
                <Ionicons
                  name={category.icon}
                  size={24}
                  color={ChatTheme.accent}
                />
              </View>
              <Text style={styles.categoryTitle}>{category.title}</Text>
              <Ionicons
                name="chevron-forward"
                size={20}
                color={ChatTheme.textSecondary}
              />
            </TouchableOpacity>
          ))}
        </View>

        {/* Placeholder for future content */}
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Coming Soon</Text>
          <View style={styles.placeholderCard}>
            <Ionicons
              name="rocket-outline"
              size={48}
              color={ChatTheme.textSecondary}
            />
            <Text style={styles.placeholderText}>
              More features coming soon!
            </Text>
          </View>
        </View>
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: ChatTheme.background,
  },
  header: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    paddingHorizontal: ChatTheme.spacing.lg,
    paddingVertical: ChatTheme.spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: ChatTheme.border,
  },
  headerTitle: {
    fontSize: 24,
    fontWeight: "700",
    color: ChatTheme.textPrimary,
    fontFamily: ChatTheme.fonts.bold,
  },
  content: {
    flex: 1,
  },
  section: {
    padding: ChatTheme.spacing.lg,
  },
  sectionTitle: {
    fontSize: 18,
    fontWeight: "600",
    color: ChatTheme.textPrimary,
    fontFamily: ChatTheme.fonts.semibold,
    marginBottom: ChatTheme.spacing.md,
  },
  categoryCard: {
    flexDirection: "row",
    alignItems: "center",
    backgroundColor: ChatTheme.messageBackground,
    padding: ChatTheme.spacing.md,
    borderRadius: ChatTheme.borderRadius.md,
    marginBottom: ChatTheme.spacing.sm,
    borderWidth: 1,
    borderColor: ChatTheme.border,
  },
  categoryIcon: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: "rgba(22, 193, 255, 0.1)",
    alignItems: "center",
    justifyContent: "center",
    marginRight: ChatTheme.spacing.md,
  },
  categoryTitle: {
    flex: 1,
    fontSize: 16,
    fontWeight: "500",
    color: ChatTheme.textPrimary,
    fontFamily: ChatTheme.fonts.medium,
  },
  placeholderCard: {
    backgroundColor: ChatTheme.messageBackground,
    padding: ChatTheme.spacing.xl,
    borderRadius: ChatTheme.borderRadius.lg,
    alignItems: "center",
    justifyContent: "center",
    borderWidth: 1,
    borderColor: ChatTheme.border,
  },
  placeholderText: {
    marginTop: ChatTheme.spacing.md,
    fontSize: 16,
    color: ChatTheme.textSecondary,
    fontFamily: ChatTheme.fonts.regular,
  },
});
