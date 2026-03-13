import { useRouter } from "expo-router";
import { useCallback, useMemo, useState } from "react";
import {
  ActivityIndicator,
  Pressable,
  RefreshControl,
  SectionList,
  TextInput,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import {
  AppIcon,
  ArrowLeft01Icon,
  Search01Icon,
  ToolsIcon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import type { Tool } from "../api/tools-api";
import type { GroupedTools } from "../hooks/useTools";
import { useTools } from "../hooks/useTools";
import { ToolCard } from "./ToolCard";

// ─── Section Header ───────────────────────────────────────────────────────────

interface SectionHeaderProps {
  title: string;
  count: number;
}

function SectionHeader({ title, count }: SectionHeaderProps) {
  const { fontSize, spacing } = useResponsive();
  return (
    <View
      style={{
        flexDirection: "row",
        alignItems: "center",
        gap: 8,
        paddingHorizontal: spacing.md,
        paddingTop: spacing.lg,
        paddingBottom: spacing.sm,
        backgroundColor: "#131416",
      }}
    >
      <Text
        style={{
          fontSize: fontSize.sm,
          fontWeight: "600",
          color: "#f4f4f5",
        }}
      >
        {title}
      </Text>
      <View
        style={{
          backgroundColor: "rgba(255,255,255,0.08)",
          borderRadius: 999,
          minWidth: 22,
          height: 20,
          alignItems: "center",
          justifyContent: "center",
          paddingHorizontal: 6,
        }}
      >
        <Text
          style={{
            fontSize: fontSize.xs - 1,
            fontWeight: "500",
            color: "#8e8e93",
          }}
        >
          {count}
        </Text>
      </View>
    </View>
  );
}

// ─── Empty State ──────────────────────────────────────────────────────────────

function EmptyState({ query }: { query: string }) {
  const { fontSize, spacing } = useResponsive();
  return (
    <View
      style={{
        flex: 1,
        alignItems: "center",
        justifyContent: "center",
        paddingVertical: spacing.xl * 3,
        gap: spacing.sm,
      }}
    >
      <AppIcon icon={ToolsIcon} size={48} color="#3a3a3c" />
      <Text
        style={{
          fontSize: fontSize.base,
          fontWeight: "500",
          color: "#d4d4d8",
          textAlign: "center",
        }}
      >
        {query ? `No results for "${query}"` : "No tools available"}
      </Text>
      <Text
        style={{
          fontSize: fontSize.sm,
          color: "#8e8e93",
          textAlign: "center",
        }}
      >
        {query
          ? "Try a different search term"
          : "Connect integrations to unlock tools"}
      </Text>
    </View>
  );
}

// ─── Loading Skeleton ─────────────────────────────────────────────────────────

function SkeletonCard() {
  const { spacing, moderateScale } = useResponsive();
  return (
    <View
      style={{
        backgroundColor: "rgba(23,25,32,1)",
        borderRadius: moderateScale(16, 0.5),
        padding: spacing.md,
        gap: spacing.sm,
        marginHorizontal: spacing.md,
        marginBottom: 8,
      }}
    >
      <View
        style={{ flexDirection: "row", alignItems: "center", gap: spacing.sm }}
      >
        <View
          style={{
            width: 40,
            height: 40,
            borderRadius: moderateScale(10, 0.5),
            backgroundColor: "rgba(255,255,255,0.06)",
          }}
        />
        <View style={{ flex: 1, gap: 6 }}>
          <View
            style={{
              height: 14,
              width: "55%",
              backgroundColor: "rgba(255,255,255,0.06)",
              borderRadius: 6,
            }}
          />
          <View
            style={{
              height: 10,
              width: "25%",
              backgroundColor: "rgba(255,255,255,0.04)",
              borderRadius: 4,
            }}
          />
        </View>
      </View>
      <View
        style={{
          height: 10,
          width: "85%",
          backgroundColor: "rgba(255,255,255,0.04)",
          borderRadius: 4,
        }}
      />
    </View>
  );
}

function LoadingSkeleton() {
  const { spacing } = useResponsive();
  return (
    <View style={{ paddingTop: spacing.md }}>
      {[1, 2].map((groupIdx) => (
        <View key={groupIdx}>
          <View
            style={{
              height: 14,
              width: 100,
              backgroundColor: "rgba(255,255,255,0.06)",
              borderRadius: 6,
              marginHorizontal: spacing.md,
              marginBottom: spacing.sm,
              marginTop: spacing.lg,
            }}
          />
          {[1, 2, 3].map((cardIdx) => (
            <SkeletonCard key={cardIdx} />
          ))}
        </View>
      ))}
    </View>
  );
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

function formatCategoryLabel(category: string): string {
  if (category === "ai-ml") return "AI & ML";
  return category
    .split(/[-_]/)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

// ─── Main Screen ──────────────────────────────────────────────────────────────

export function ToolsScreen() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { spacing, fontSize, moderateScale } = useResponsive();

  const [searchQuery, setSearchQuery] = useState("");

  const { tools, groupedTools, isLoading, isRefreshing, refresh } = useTools();

  const q = searchQuery.trim().toLowerCase();

  const filteredSections = useMemo<
    Array<{ title: string; data: Tool[] }>
  >(() => {
    let sections: GroupedTools[];

    if (q) {
      sections = groupedTools
        .map((group) => ({
          ...group,
          tools: group.tools.filter(
            (t) =>
              t.name.toLowerCase().includes(q) ||
              t.description.toLowerCase().includes(q),
          ),
        }))
        .filter((g) => g.tools.length > 0);
    } else {
      sections = groupedTools;
    }

    return sections.map((g) => ({
      title: formatCategoryLabel(g.category),
      data: g.tools,
    }));
  }, [groupedTools, q]);

  const _totalVisible = filteredSections.reduce(
    (sum, s) => sum + s.data.length,
    0,
  );

  const renderSectionHeader = useCallback(
    ({ section }: { section: { title: string; data: Tool[] } }) => (
      <SectionHeader title={section.title} count={section.data.length} />
    ),
    [],
  );

  const renderItem = useCallback(
    ({ item }: { item: Tool }) => (
      <View style={{ paddingHorizontal: spacing.md, marginBottom: 8 }}>
        <ToolCard tool={item} />
      </View>
    ),
    [spacing.md],
  );

  const keyExtractor = useCallback((item: Tool) => `tool-${item.id}`, []);

  return (
    <View style={{ flex: 1, backgroundColor: "#131416" }}>
      {/* ─── Header ─────────────────────────────────────────────────────── */}
      <View
        style={{
          paddingTop: insets.top + spacing.sm,
          paddingHorizontal: spacing.md,
          paddingBottom: spacing.md,
          borderBottomWidth: 1,
          borderBottomColor: "rgba(255,255,255,0.08)",
          gap: spacing.md,
        }}
      >
        <View style={{ flexDirection: "row", alignItems: "center" }}>
          <Pressable
            onPress={() => router.back()}
            style={{
              width: 36,
              height: 36,
              borderRadius: 999,
              alignItems: "center",
              justifyContent: "center",
              backgroundColor: "rgba(255,255,255,0.05)",
            }}
          >
            <AppIcon icon={ArrowLeft01Icon} size={18} color="#fff" />
          </Pressable>

          <Text
            style={{
              marginLeft: spacing.md,
              fontSize: fontSize.base,
              fontWeight: "600",
              color: "#fff",
              flex: 1,
            }}
          >
            Tools
          </Text>

          {isLoading && !isRefreshing ? (
            <ActivityIndicator size="small" color="#00bbff" />
          ) : (
            <Text style={{ fontSize: fontSize.xs, color: "#8e8e93" }}>
              {tools.length} total
            </Text>
          )}
        </View>

        {/* Search bar */}
        <View
          style={{
            flexDirection: "row",
            alignItems: "center",
            backgroundColor: "rgba(255,255,255,0.06)",
            borderRadius: moderateScale(14, 0.5),
            paddingHorizontal: spacing.sm + 4,
            paddingVertical: spacing.sm,
            gap: spacing.sm,
          }}
        >
          <AppIcon icon={Search01Icon} size={16} color="#6f737c" />
          <TextInput
            value={searchQuery}
            onChangeText={setSearchQuery}
            placeholder="Search tools..."
            placeholderTextColor="#6f737c"
            style={{
              flex: 1,
              color: "#fff",
              fontSize: fontSize.sm,
              padding: 0,
            }}
            returnKeyType="search"
            clearButtonMode="while-editing"
          />
        </View>
      </View>

      {/* ─── Content ─────────────────────────────────────────────────────── */}
      {isLoading && !isRefreshing ? (
        <LoadingSkeleton />
      ) : (
        <SectionList
          sections={filteredSections}
          keyExtractor={keyExtractor}
          renderItem={renderItem}
          renderSectionHeader={renderSectionHeader}
          ListEmptyComponent={<EmptyState query={q} />}
          contentContainerStyle={{
            paddingTop: spacing.xs,
            paddingBottom: insets.bottom + spacing.xl,
            flexGrow: 1,
          }}
          refreshControl={
            <RefreshControl
              refreshing={isRefreshing}
              onRefresh={() => void refresh()}
              tintColor="#00bbff"
            />
          }
          showsVerticalScrollIndicator={false}
          keyboardShouldPersistTaps="handled"
          keyboardDismissMode="on-drag"
          stickySectionHeadersEnabled
        />
      )}
    </View>
  );
}
