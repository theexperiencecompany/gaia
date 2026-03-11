import { Image } from "expo-image";
import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useMemo, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  FlatList,
  Pressable,
  RefreshControl,
  ScrollView,
  TextInput,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import {
  AppIcon,
  ArrowLeft01Icon,
  CheckmarkCircle02Icon,
  ConnectIcon,
  Search01Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import {
  connectIntegration,
  disconnectIntegration,
  fetchIntegrations,
} from "../api";
import type { Integration } from "../types";

// ─── Constants ──────────────────────────────────────────────────────────────

const CATEGORY_LABELS: Record<string, string> = {
  all: "All",
  productivity: "Productivity",
  developer: "Developer",
  communication: "Communication",
  analytics: "Analytics",
  finance: "Finance",
  "ai-ml": "AI & ML",
  education: "Education",
  personal: "Personal",
  capabilities: "Capabilities",
  other: "Other",
};

function getCategoryLabel(categoryId: string): string {
  if (CATEGORY_LABELS[categoryId]) return CATEGORY_LABELS[categoryId];
  return categoryId
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

const INTEGRATION_LOGOS: Record<string, string> = {
  googlecalendar:
    "https://upload.wikimedia.org/wikipedia/commons/thumb/a/a5/Google_Calendar_icon_%282020%29.svg/512px-Google_Calendar_icon_%282020%29.svg.png",
  googledocs:
    "https://upload.wikimedia.org/wikipedia/commons/thumb/0/01/Google_Docs_logo_%282020%29.svg/512px-Google_Docs_logo_%282020%29.svg.png",
  gmail:
    "https://upload.wikimedia.org/wikipedia/commons/thumb/7/7e/Gmail_icon_%282020%29.svg/512px-Gmail_icon_%282020%29.svg.png",
  notion:
    "https://upload.wikimedia.org/wikipedia/commons/thumb/e/e9/Notion-logo.svg/512px-Notion-logo.svg.png",
  twitter:
    "https://upload.wikimedia.org/wikipedia/commons/thumb/6/6f/Logo_of_Twitter.svg/512px-Logo_of_Twitter.svg.png",
  googlesheets:
    "https://upload.wikimedia.org/wikipedia/commons/thumb/a/a0/Google_Sheets_logo_%282020%29.svg/512px-Google_Sheets_logo_%282020%29.svg.png",
  linkedin:
    "https://upload.wikimedia.org/wikipedia/commons/thumb/c/ca/LinkedIn_logo_initials.png/512px-LinkedIn_logo_initials.png",
  github:
    "https://upload.wikimedia.org/wikipedia/commons/thumb/c/c2/GitHub_Invertocat_Logo.svg/512px-GitHub_Invertocat_Logo.svg.png",
  reddit:
    "https://upload.wikimedia.org/wikipedia/commons/thumb/b/b4/Reddit_logo.svg/512px-Reddit_logo.svg.png",
  airtable:
    "https://upload.wikimedia.org/wikipedia/commons/thumb/4/4b/Airtable_Logo.svg/512px-Airtable_Logo.svg.png",
  linear:
    "https://upload.wikimedia.org/wikipedia/commons/thumb/5/59/Linear_logo.svg/512px-Linear_logo.svg.png",
  slack:
    "https://upload.wikimedia.org/wikipedia/commons/thumb/d/d5/Slack_icon_2019.svg/512px-Slack_icon_2019.svg.png",
  hubspot:
    "https://upload.wikimedia.org/wikipedia/commons/thumb/3/3f/HubSpot_Logo.svg/512px-HubSpot_Logo.svg.png",
  googletasks:
    "https://upload.wikimedia.org/wikipedia/commons/thumb/5/5b/Google_Tasks_2021.svg/512px-Google_Tasks_2021.svg.png",
  todoist:
    "https://upload.wikimedia.org/wikipedia/commons/thumb/6/6d/Todoist_logo.svg/512px-Todoist_logo.svg.png",
  googlemeet:
    "https://upload.wikimedia.org/wikipedia/commons/thumb/9/9b/Google_Meet_icon_%282020%29.svg/512px-Google_Meet_icon_%282020%29.svg.png",
  google_maps:
    "https://upload.wikimedia.org/wikipedia/commons/thumb/a/aa/Google_Maps_icon_%282020%29.svg/512px-Google_Maps_icon_%282020%29.svg.png",
  asana:
    "https://upload.wikimedia.org/wikipedia/commons/thumb/3/3b/Asana_logo.svg/512px-Asana_logo.svg.png",
  trello:
    "https://upload.wikimedia.org/wikipedia/commons/thumb/7/7a/Trello-logo-blue.svg/512px-Trello-logo-blue.svg.png",
  instagram:
    "https://upload.wikimedia.org/wikipedia/commons/thumb/e/e7/Instagram_logo_2016.svg/512px-Instagram_logo_2016.svg.png",
  clickup:
    "https://upload.wikimedia.org/wikipedia/commons/thumb/7/75/ClickUp_Logo.svg/512px-ClickUp_Logo.svg.png",
};

function getLogoUri(integration: Integration): string {
  if (integration.iconUrl) return integration.iconUrl;
  return (
    INTEGRATION_LOGOS[integration.id] ??
    "https://upload.wikimedia.org/wikipedia/commons/thumb/a/ac/No_image_available.svg/512px-No_image_available.svg.png"
  );
}

// ─── Integration Row ─────────────────────────────────────────────────────────

interface IntegrationRowProps {
  integration: Integration;
  connectingId: string | null;
  onPress: (integration: Integration) => void;
}

function IntegrationRow({
  integration,
  connectingId,
  onPress,
}: IntegrationRowProps) {
  const { fontSize, spacing, moderateScale } = useResponsive();
  const isConnected = integration.status === "connected";
  const isPending = integration.status === "created";
  const isConnecting = connectingId === integration.id;
  const isAvailable =
    integration.source === "custom" || integration.available !== false;

  return (
    <Pressable
      onPress={() => onPress(integration)}
      disabled={isConnecting}
      style={({ pressed }) => ({
        flexDirection: "row",
        alignItems: "center",
        paddingHorizontal: spacing.md,
        paddingVertical: spacing.sm + 4,
        backgroundColor: pressed
          ? "rgba(255,255,255,0.04)"
          : "rgba(23,25,32,1)",
        borderRadius: moderateScale(16, 0.5),
        opacity: isConnecting ? 0.6 : 1,
      })}
    >
      {/* Logo */}
      <View
        style={{
          width: 44,
          height: 44,
          borderRadius: moderateScale(12, 0.5),
          backgroundColor: "rgba(255,255,255,0.06)",
          alignItems: "center",
          justifyContent: "center",
          marginRight: spacing.md,
          flexShrink: 0,
        }}
      >
        <Image
          source={{ uri: getLogoUri(integration) }}
          style={{ width: 28, height: 28 }}
          contentFit="contain"
        />
      </View>

      {/* Name + description */}
      <View style={{ flex: 1, minWidth: 0, marginRight: spacing.sm }}>
        <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
          <Text
            style={{
              fontSize: fontSize.sm,
              fontWeight: "500",
              color: "#f4f4f5",
              flexShrink: 1,
            }}
            numberOfLines={1}
          >
            {integration.name}
          </Text>
          {isPending && (
            <View
              style={{
                width: 6,
                height: 6,
                borderRadius: 3,
                backgroundColor: "#f59e0b",
              }}
            />
          )}
        </View>
        <Text
          style={{
            fontSize: fontSize.xs,
            color: "#8e8e93",
            marginTop: 2,
          }}
          numberOfLines={1}
        >
          {integration.description}
        </Text>
      </View>

      {/* Status / action */}
      {isConnecting ? (
        <ActivityIndicator size="small" color="#8e8e93" />
      ) : isConnected ? (
        <View
          style={{
            flexDirection: "row",
            alignItems: "center",
            gap: 5,
            backgroundColor: "rgba(52,199,89,0.12)",
            borderRadius: moderateScale(20, 0.5),
            paddingHorizontal: spacing.sm + 2,
            paddingVertical: 5,
          }}
        >
          <AppIcon icon={CheckmarkCircle02Icon} size={12} color="#34c759" />
          <Text
            style={{
              fontSize: fontSize.xs,
              color: "#34c759",
              fontWeight: "500",
            }}
          >
            Connected
          </Text>
        </View>
      ) : isAvailable ? (
        <View
          style={{
            backgroundColor: "rgba(0,187,255,0.12)",
            borderRadius: moderateScale(20, 0.5),
            paddingHorizontal: spacing.sm + 2,
            paddingVertical: 5,
          }}
        >
          <Text
            style={{
              fontSize: fontSize.xs,
              color: "#00bbff",
              fontWeight: "500",
            }}
          >
            Connect
          </Text>
        </View>
      ) : null}
    </Pressable>
  );
}

// ─── Category Chips ───────────────────────────────────────────────────────────

interface CategoryChipsProps {
  categories: string[];
  selected: string;
  onSelect: (cat: string) => void;
}

function CategoryChips({ categories, selected, onSelect }: CategoryChipsProps) {
  const { fontSize, spacing, moderateScale } = useResponsive();
  const allCategories = ["all", ...categories];

  return (
    <ScrollView
      horizontal
      showsHorizontalScrollIndicator={false}
      contentContainerStyle={{ gap: 8, paddingHorizontal: spacing.md }}
    >
      {allCategories.map((cat) => {
        const isActive = selected === cat;
        return (
          <Pressable
            key={cat}
            onPress={() => onSelect(cat)}
            style={{
              borderRadius: moderateScale(20, 0.5),
              paddingHorizontal: spacing.md,
              paddingVertical: 6,
              backgroundColor: isActive
                ? "rgba(0,187,255,0.18)"
                : "rgba(255,255,255,0.07)",
            }}
          >
            <Text
              style={{
                fontSize: fontSize.xs,
                fontWeight: isActive ? "600" : "400",
                color: isActive ? "#00bbff" : "#8e8e93",
              }}
            >
              {getCategoryLabel(cat)}
            </Text>
          </Pressable>
        );
      })}
    </ScrollView>
  );
}

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
      <AppIcon icon={ConnectIcon} size={48} color="#3a3a3c" />
      <Text
        style={{
          fontSize: fontSize.base,
          fontWeight: "500",
          color: "#d4d4d8",
          textAlign: "center",
        }}
      >
        {query ? `No results for "${query}"` : "No integrations found"}
      </Text>
      <Text
        style={{
          fontSize: fontSize.sm,
          color: "#8e8e93",
          textAlign: "center",
        }}
      >
        {query ? "Try a different search term" : "Check back later"}
      </Text>
    </View>
  );
}

// ─── Main Screen ──────────────────────────────────────────────────────────────

type ListItem =
  | { type: "section-header"; category: string; count: number }
  | { type: "integration"; integration: Integration };

export function IntegrationsScreen() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { spacing, fontSize, moderateScale } = useResponsive();

  const [integrations, setIntegrations] = useState<Integration[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedCategory, setSelectedCategory] = useState("all");
  const [connectingId, setConnectingId] = useState<string | null>(null);

  const load = useCallback(async (refresh = false) => {
    if (refresh) {
      setIsRefreshing(true);
    } else {
      setIsLoading(true);
    }
    try {
      const data = await fetchIntegrations();
      setIntegrations(data);
    } catch {
      // Silent fail - already handled in API layer
    } finally {
      setIsLoading(false);
      setIsRefreshing(false);
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      void load();
    }, [load]),
  );

  // Derive categories from data
  const availableCategories = useMemo(() => {
    const cats = new Set(integrations.map((i) => i.category));
    const CATEGORY_ORDER: Record<string, number> = {
      productivity: 0,
      developer: 1,
      communication: 2,
      analytics: 3,
      finance: 4,
      "ai-ml": 5,
      education: 6,
      personal: 7,
      capabilities: 8,
      other: 99,
    };
    return Array.from(cats).sort(
      (a, b) => (CATEGORY_ORDER[a] ?? 50) - (CATEGORY_ORDER[b] ?? 50),
    );
  }, [integrations]);

  // Filter by search query + category
  const filteredIntegrations = useMemo(() => {
    let results = integrations;

    if (selectedCategory !== "all") {
      results = results.filter((i) => i.category === selectedCategory);
    }

    const q = searchQuery.trim().toLowerCase();
    if (q) {
      results = results.filter(
        (i) =>
          i.name.toLowerCase().includes(q) ||
          i.description.toLowerCase().includes(q),
      );
    }

    return results;
  }, [integrations, selectedCategory, searchQuery]);

  const connectedCount = useMemo(
    () => integrations.filter((i) => i.status === "connected").length,
    [integrations],
  );

  // Build flat list items: section headers + rows
  const listItems = useMemo<ListItem[]>(() => {
    if (selectedCategory !== "all") {
      // Single category view - no section headers
      return filteredIntegrations.map((integration) => ({
        type: "integration" as const,
        integration,
      }));
    }

    // Group by category and inject headers
    const grouped: Record<string, Integration[]> = {};
    for (const integration of filteredIntegrations) {
      const cat = integration.category;
      if (!grouped[cat]) grouped[cat] = [];
      grouped[cat].push(integration);
    }

    const items: ListItem[] = [];
    const orderedCats = availableCategories.filter(
      (cat) => grouped[cat]?.length,
    );

    for (const cat of orderedCats) {
      const catIntegrations = grouped[cat];
      items.push({
        type: "section-header",
        category: cat,
        count: catIntegrations.length,
      });
      for (const integration of catIntegrations) {
        items.push({ type: "integration", integration });
      }
    }

    return items;
  }, [filteredIntegrations, selectedCategory, availableCategories]);

  const handleIntegrationPress = useCallback(
    async (integration: Integration) => {
      if (connectingId) return;

      if (integration.status === "connected") {
        Alert.alert(
          "Disconnect Integration",
          `Disconnect ${integration.name}?`,
          [
            { text: "Cancel", style: "cancel" },
            {
              text: "Disconnect",
              style: "destructive",
              onPress: async () => {
                setConnectingId(integration.id);
                const success = await disconnectIntegration(integration.id);
                if (!success) {
                  Alert.alert("Error", "Failed to disconnect integration");
                } else {
                  await load();
                }
                setConnectingId(null);
              },
            },
          ],
        );
      } else {
        setConnectingId(integration.id);
        const result = await connectIntegration(integration.id);
        if (result.success) {
          await load();
        } else if (!result.cancelled) {
          Alert.alert("Error", result.error ?? "Failed to connect integration");
        }
        setConnectingId(null);
      }
    },
    [connectingId, load],
  );

  const renderItem = useCallback(
    ({ item }: { item: ListItem }) => {
      if (item.type === "section-header") {
        return (
          <SectionHeader
            title={getCategoryLabel(item.category)}
            count={item.count}
          />
        );
      }
      return (
        <View style={{ paddingHorizontal: spacing.md, marginBottom: 8 }}>
          <IntegrationRow
            integration={item.integration}
            connectingId={connectingId}
            onPress={handleIntegrationPress}
          />
        </View>
      );
    },
    [connectingId, handleIntegrationPress, spacing.md],
  );

  const keyExtractor = useCallback((item: ListItem) => {
    if (item.type === "section-header") return `header-${item.category}`;
    return `integration-${item.integration.id}`;
  }, []);

  const ListHeader = useCallback(
    () => (
      <View style={{ gap: spacing.sm, paddingBottom: spacing.sm }}>
        {/* Stats bar */}
        <View
          style={{
            flexDirection: "row",
            alignItems: "center",
            justifyContent: "space-between",
            paddingHorizontal: spacing.md,
          }}
        >
          <Text style={{ fontSize: fontSize.xs, color: "#8e8e93" }}>
            {connectedCount} of {integrations.length} connected
          </Text>
        </View>

        {/* Category chips */}
        {availableCategories.length > 1 && (
          <CategoryChips
            categories={availableCategories}
            selected={selectedCategory}
            onSelect={(cat) => {
              setSelectedCategory(cat);
            }}
          />
        )}
      </View>
    ),
    [
      connectedCount,
      integrations.length,
      availableCategories,
      selectedCategory,
      spacing.md,
      spacing.sm,
      fontSize.xs,
    ],
  );

  const ListEmpty = useCallback(
    () =>
      isLoading ? (
        <View
          style={{
            paddingVertical: spacing.xl * 3,
            alignItems: "center",
            gap: spacing.md,
          }}
        >
          <ActivityIndicator size="large" color="#00bbff" />
          <Text style={{ fontSize: fontSize.sm, color: "#8e8e93" }}>
            Loading integrations...
          </Text>
        </View>
      ) : (
        <EmptyState query={searchQuery} />
      ),
    [isLoading, searchQuery, spacing.xl, spacing.md, fontSize.sm],
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
            Integrations
          </Text>
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
            onChangeText={(text) => {
              setSearchQuery(text);
              if (text && selectedCategory !== "all") {
                setSelectedCategory("all");
              }
            }}
            placeholder="Search integrations..."
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
      <FlatList
        data={listItems}
        keyExtractor={keyExtractor}
        renderItem={renderItem}
        ListHeaderComponent={ListHeader}
        ListEmptyComponent={ListEmpty}
        contentContainerStyle={{
          paddingTop: spacing.md,
          paddingBottom: insets.bottom + spacing.xl,
          flexGrow: 1,
        }}
        refreshControl={
          <RefreshControl
            refreshing={isRefreshing}
            onRefresh={() => void load(true)}
            tintColor="#00bbff"
          />
        }
        showsVerticalScrollIndicator={false}
        keyboardShouldPersistTaps="handled"
        keyboardDismissMode="on-drag"
      />
    </View>
  );
}
