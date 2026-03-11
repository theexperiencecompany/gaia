import { useRouter } from "expo-router";
import { useCallback, useMemo, useState } from "react";
import {
  ActivityIndicator,
  FlatList,
  Pressable,
  RefreshControl,
  TextInput,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { AppIcon, ArrowLeft01Icon, Search01Icon } from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import type { Skill } from "../api/skills-api";
import { useSkills } from "../hooks/useSkills";
import { SkillCard } from "./SkillCard";

// ─── Types ────────────────────────────────────────────────────────────────────

type ListItem =
  | { type: "section-header"; title: string; count: number }
  | { type: "skill"; skill: Skill }
  | { type: "empty"; section: "my-skills" | "discover" };

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

interface EmptySectionProps {
  section: "my-skills" | "discover";
  hasSearch: boolean;
}

function EmptySection({ section, hasSearch }: EmptySectionProps) {
  const { fontSize, spacing } = useResponsive();
  const message =
    section === "my-skills"
      ? hasSearch
        ? "No skills match your search"
        : "No skills enabled yet"
      : hasSearch
        ? "No skills found for this search"
        : "No skills available to discover";

  const subtitle =
    section === "my-skills"
      ? hasSearch
        ? "Try a different search term"
        : "Enable skills from the Discover section below"
      : hasSearch
        ? "Try a different search term"
        : "Check back later for new skills";

  return (
    <View
      style={{
        alignItems: "center",
        paddingVertical: spacing.xl,
        paddingHorizontal: spacing.md,
        gap: spacing.xs,
      }}
    >
      <Text
        style={{
          fontSize: fontSize.sm,
          color: "#5a5a5e",
          textAlign: "center",
        }}
      >
        {message}
      </Text>
      <Text
        style={{
          fontSize: fontSize.xs,
          color: "#3a3a3c",
          textAlign: "center",
        }}
      >
        {subtitle}
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
              width: "60%",
              backgroundColor: "rgba(255,255,255,0.06)",
              borderRadius: 6,
            }}
          />
          <View
            style={{
              height: 10,
              width: "30%",
              backgroundColor: "rgba(255,255,255,0.04)",
              borderRadius: 4,
            }}
          />
        </View>
      </View>
      <View
        style={{
          height: 10,
          width: "90%",
          backgroundColor: "rgba(255,255,255,0.04)",
          borderRadius: 4,
        }}
      />
    </View>
  );
}

// ─── Main Screen ──────────────────────────────────────────────────────────────

export function SkillsScreen() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { spacing, fontSize, moderateScale } = useResponsive();

  const [searchQuery, setSearchQuery] = useState("");

  const { mySkills, discoverableSkills, isLoading, isRefreshing, refresh } =
    useSkills();

  const [localMySkills, setLocalMySkills] = useState<Skill[] | null>(null);
  const [localDiscoverSkills, setLocalDiscoverSkills] = useState<
    Skill[] | null
  >(null);

  const effectiveMySkills = localMySkills ?? mySkills;
  const effectiveDiscoverSkills = localDiscoverSkills ?? discoverableSkills;

  const handleToggle = useCallback(
    (skill: Skill, enabled: boolean) => {
      setLocalMySkills((prev) => {
        const base = prev ?? mySkills;
        if (enabled) {
          const exists = base.some((s) => s.id === skill.id);
          return exists
            ? base.map((s) => (s.id === skill.id ? { ...s, enabled } : s))
            : [...base, { ...skill, enabled }];
        }
        return base.map((s) => (s.id === skill.id ? { ...s, enabled } : s));
      });
      setLocalDiscoverSkills((prev) => {
        const base = prev ?? discoverableSkills;
        return base.map((s) => (s.id === skill.id ? { ...s, enabled } : s));
      });
    },
    [mySkills, discoverableSkills],
  );

  const handleRefresh = useCallback(async () => {
    setLocalMySkills(null);
    setLocalDiscoverSkills(null);
    await refresh();
  }, [refresh]);

  const q = searchQuery.trim().toLowerCase();

  const filteredMySkills = useMemo(() => {
    if (!q) return effectiveMySkills;
    return effectiveMySkills.filter(
      (s) =>
        s.name.toLowerCase().includes(q) ||
        s.description.toLowerCase().includes(q),
    );
  }, [effectiveMySkills, q]);

  const filteredDiscoverSkills = useMemo(() => {
    if (!q) return effectiveDiscoverSkills;
    return effectiveDiscoverSkills.filter(
      (s) =>
        s.name.toLowerCase().includes(q) ||
        s.description.toLowerCase().includes(q),
    );
  }, [effectiveDiscoverSkills, q]);

  const listItems = useMemo<ListItem[]>(() => {
    const items: ListItem[] = [];

    items.push({
      type: "section-header",
      title: "My Skills",
      count: filteredMySkills.length,
    });

    if (filteredMySkills.length === 0) {
      items.push({ type: "empty", section: "my-skills" });
    } else {
      for (const skill of filteredMySkills) {
        items.push({ type: "skill", skill });
      }
    }

    items.push({
      type: "section-header",
      title: "Discover",
      count: filteredDiscoverSkills.length,
    });

    if (filteredDiscoverSkills.length === 0) {
      items.push({ type: "empty", section: "discover" });
    } else {
      for (const skill of filteredDiscoverSkills) {
        items.push({ type: "skill", skill });
      }
    }

    return items;
  }, [filteredMySkills, filteredDiscoverSkills]);

  const keyExtractor = useCallback((item: ListItem, index: number) => {
    if (item.type === "section-header") return `header-${item.title}`;
    if (item.type === "empty") return `empty-${item.section}`;
    return `skill-${item.skill.id}-${index}`;
  }, []);

  const renderItem = useCallback(
    ({ item }: { item: ListItem }) => {
      if (item.type === "section-header") {
        return <SectionHeader title={item.title} count={item.count} />;
      }
      if (item.type === "empty") {
        return <EmptySection section={item.section} hasSearch={q.length > 0} />;
      }
      return (
        <View style={{ paddingHorizontal: spacing.md, marginBottom: 8 }}>
          <SkillCard skill={item.skill} onToggle={handleToggle} />
        </View>
      );
    },
    [spacing.md, handleToggle, q],
  );

  const ListEmpty = useCallback(
    () =>
      isLoading ? (
        <View style={{ paddingTop: spacing.md }}>
          <SkeletonCard />
          <SkeletonCard />
          <SkeletonCard />
        </View>
      ) : null,
    [isLoading, spacing.md],
  );

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
            Skills
          </Text>

          {isLoading && !isRefreshing && (
            <ActivityIndicator size="small" color="#00bbff" />
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
            placeholder="Search skills..."
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

      {/* ─── List ────────────────────────────────────────────────────────── */}
      {isLoading && !isRefreshing ? (
        <View style={{ paddingTop: spacing.md }}>
          <View
            style={{
              height: 14,
              width: 80,
              backgroundColor: "rgba(255,255,255,0.06)",
              borderRadius: 6,
              marginHorizontal: spacing.md,
              marginBottom: spacing.sm,
              marginTop: spacing.lg,
            }}
          />
          <SkeletonCard />
          <SkeletonCard />
          <View
            style={{
              height: 14,
              width: 80,
              backgroundColor: "rgba(255,255,255,0.06)",
              borderRadius: 6,
              marginHorizontal: spacing.md,
              marginBottom: spacing.sm,
              marginTop: spacing.lg,
            }}
          />
          <SkeletonCard />
          <SkeletonCard />
          <SkeletonCard />
        </View>
      ) : (
        <FlatList
          data={listItems}
          keyExtractor={keyExtractor}
          renderItem={renderItem}
          ListEmptyComponent={ListEmpty}
          contentContainerStyle={{
            paddingTop: spacing.xs,
            paddingBottom: insets.bottom + spacing.xl,
            flexGrow: 1,
          }}
          refreshControl={
            <RefreshControl
              refreshing={isRefreshing}
              onRefresh={() => void handleRefresh()}
              tintColor="#00bbff"
            />
          }
          showsVerticalScrollIndicator={false}
          keyboardShouldPersistTaps="handled"
          keyboardDismissMode="on-drag"
        />
      )}
    </View>
  );
}
