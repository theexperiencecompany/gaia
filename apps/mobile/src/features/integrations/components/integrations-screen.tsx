import { Image } from "expo-image";
import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useMemo, useRef, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  FlatList,
  Pressable,
  RefreshControl,
  ScrollView,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import {
  AppIcon,
  ArrowLeft01Icon,
  CheckmarkCircle02Icon,
  ConnectIcon,
  InformationCircleIcon,
  PlusSignIcon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import {
  AppEmptyStateCard,
  AppFilterChipGroup,
  AppSearchInput,
  AppSectionCard,
  AppStatusChip,
} from "@/shared/components/ui";
import {
  connectIntegration,
  disconnectIntegration,
  fetchIntegrations,
} from "../api";
import type { Integration } from "../types";
import { BearerTokenSheet, type BearerTokenSheetRef } from "./BearerTokenSheet";
import {
  CreateMCPIntegrationSheet,
  type CreateMCPIntegrationSheetRef,
} from "./CreateMCPIntegrationSheet";

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
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
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

function getLogoUri(integration: Integration): string | null {
  if (integration.iconUrl) return integration.iconUrl;
  return INTEGRATION_LOGOS[integration.id] ?? null;
}

interface IntegrationRowProps {
  integration: Integration;
  connectingId: string | null;
  onPress: (integration: Integration) => Promise<void>;
}

function LogoCircle({
  integration,
  size,
  borderRadius,
}: {
  integration: Integration;
  size: number;
  borderRadius: number;
}) {
  const initial = integration.name.charAt(0).toUpperCase();
  const logoUri = getLogoUri(integration);

  // Generate a deterministic hue from the integration id for fallback circles
  const hue =
    integration.id.split("").reduce((acc, ch) => acc + ch.charCodeAt(0), 0) %
    360;
  const fallbackBg = `hsla(${hue},55%,38%,0.3)`;
  const fallbackBorder = `hsla(${hue},55%,55%,0.2)`;

  if (logoUri) {
    return (
      <View
        style={{
          width: size,
          height: size,
          borderRadius,
          backgroundColor: "rgba(255,255,255,0.05)",
          alignItems: "center",
          justifyContent: "center",
          overflow: "hidden",
          flexShrink: 0,
        }}
      >
        <Image
          source={{ uri: logoUri }}
          style={{ width: size - 12, height: size - 12 }}
          contentFit="contain"
        />
      </View>
    );
  }

  return (
    <View
      style={{
        width: size,
        height: size,
        borderRadius,
        backgroundColor: fallbackBg,
        borderWidth: 1,
        borderColor: fallbackBorder,
        alignItems: "center",
        justifyContent: "center",
        flexShrink: 0,
      }}
    >
      <Text
        style={{
          fontSize: size * 0.38,
          fontWeight: "700",
          color: `hsl(${hue},70%,80%)`,
        }}
      >
        {initial}
      </Text>
    </View>
  );
}

function AuthTypeBadge({
  authType,
}: {
  authType?: "oauth" | "bearer" | "none";
}) {
  const { fontSize } = useResponsive();
  if (!authType || authType === "none") return null;

  const label =
    authType === "oauth" ? "OAuth" : authType === "bearer" ? "Bearer" : "MCP";
  return (
    <View
      style={{
        backgroundColor: "rgba(255,255,255,0.06)",
        borderRadius: 4,
        paddingHorizontal: 5,
        paddingVertical: 2,
      }}
    >
      <Text
        style={{
          fontSize: fontSize.xs - 2,
          color: "#636369",
          fontWeight: "500",
        }}
      >
        {label}
      </Text>
    </View>
  );
}

function ManagedByBadge({
  managedBy,
}: {
  managedBy?: "self" | "composio" | "mcp" | "internal";
}) {
  const { fontSize } = useResponsive();
  if (!managedBy || managedBy === "self" || managedBy === "internal")
    return null;

  const label = managedBy === "composio" ? "Composio" : "MCP";
  return (
    <View
      style={{
        backgroundColor: "rgba(167,139,250,0.1)",
        borderRadius: 4,
        paddingHorizontal: 5,
        paddingVertical: 2,
      }}
    >
      <Text
        style={{
          fontSize: fontSize.xs - 2,
          color: "#a78bfa",
          fontWeight: "500",
        }}
      >
        {label}
      </Text>
    </View>
  );
}

function StatusPill({
  status,
  isConnecting,
  moderateScale,
  spacing,
  fontSize,
}: {
  status: Integration["status"];
  isConnecting: boolean;
  moderateScale: (size: number, factor?: number) => number;
  spacing: Record<string, number>;
  fontSize: Record<string, number>;
}) {
  if (isConnecting) {
    return <ActivityIndicator size="small" color="#8e8e93" />;
  }

  if (status === "connected") {
    return (
      <View
        style={{
          flexDirection: "row",
          alignItems: "center",
          gap: 4,
          backgroundColor: "rgba(52,199,89,0.12)",
          borderRadius: moderateScale(20, 0.5),
          paddingHorizontal: spacing.sm + 2,
          paddingVertical: 5,
        }}
      >
        <AppIcon icon={CheckmarkCircle02Icon} size={11} color="#34c759" />
        <Text
          style={{ fontSize: fontSize.xs, color: "#34c759", fontWeight: "500" }}
        >
          Connected
        </Text>
      </View>
    );
  }

  if (status === "error") {
    return (
      <View
        style={{
          flexDirection: "row",
          alignItems: "center",
          gap: 4,
          backgroundColor: "rgba(239,68,68,0.12)",
          borderRadius: moderateScale(20, 0.5),
          paddingHorizontal: spacing.sm + 2,
          paddingVertical: 5,
        }}
      >
        <AppIcon icon={InformationCircleIcon} size={11} color="#ef4444" />
        <Text
          style={{ fontSize: fontSize.xs, color: "#ef4444", fontWeight: "500" }}
        >
          Error
        </Text>
      </View>
    );
  }

  return (
    <View
      style={{
        backgroundColor: "rgba(255,255,255,0.06)",
        borderRadius: moderateScale(20, 0.5),
        paddingHorizontal: spacing.sm + 2,
        paddingVertical: 5,
      }}
    >
      <Text
        style={{ fontSize: fontSize.xs, color: "#636369", fontWeight: "500" }}
      >
        Not Connected
      </Text>
    </View>
  );
}

function IntegrationRow({
  integration,
  connectingId,
  onPress,
}: IntegrationRowProps) {
  const { fontSize, spacing, moderateScale } = useResponsive();
  const isConnected = integration.status === "connected";
  const isConnecting = connectingId === integration.id;
  const isAvailable =
    integration.source === "custom" || integration.available !== false;
  const toolCount = integration.tools?.length ?? 0;

  return (
    <Pressable
      onPress={() => onPress(integration)}
      style={({ pressed }) => ({
        flexDirection: "row",
        alignItems: "center",
        paddingHorizontal: spacing.md,
        paddingVertical: spacing.sm + 2,
        backgroundColor: pressed
          ? "rgba(255,255,255,0.04)"
          : "rgba(255,255,255,0.02)",
        borderRadius: moderateScale(14, 0.5),
        borderWidth: 1,
        borderColor: "rgba(255,255,255,0.06)",
      })}
    >
      {/* Circular logo with fallback initial */}
      <View style={{ marginRight: spacing.sm + 4 }}>
        <LogoCircle integration={integration} size={40} borderRadius={20} />
      </View>

      {/* Name + badges + status pill */}
      <View style={{ flex: 1, minWidth: 0, marginRight: spacing.sm }}>
        {/* Row 1: name + category badge */}
        <View
          style={{
            flexDirection: "row",
            alignItems: "center",
            gap: 6,
            flexWrap: "wrap",
          }}
        >
          <Text
            style={{
              fontSize: fontSize.sm,
              fontWeight: "700",
              color: "#f4f4f5",
              flexShrink: 1,
            }}
            numberOfLines={1}
          >
            {integration.name}
          </Text>
          <View
            style={{
              backgroundColor: "rgba(0,187,255,0.1)",
              borderRadius: 4,
              paddingHorizontal: 5,
              paddingVertical: 2,
            }}
          >
            <Text
              style={{
                fontSize: fontSize.xs - 2,
                color: "#00bbff",
                fontWeight: "500",
              }}
            >
              {getCategoryLabel(integration.category)}
            </Text>
          </View>
        </View>

        {/* Row 2: auth type + managed by */}
        <View
          style={{
            flexDirection: "row",
            alignItems: "center",
            gap: 4,
            marginTop: 3,
          }}
        >
          <AuthTypeBadge authType={integration.authType} />
          <ManagedByBadge managedBy={integration.managedBy} />
          {isConnected && toolCount > 0 && (
            <Text style={{ fontSize: fontSize.xs - 2, color: "#636369" }}>
              {toolCount} {toolCount === 1 ? "tool" : "tools"}
            </Text>
          )}
        </View>
      </View>

      {/* Right side: status + action button */}
      <View style={{ alignItems: "flex-end", gap: 6 }}>
        <StatusPill
          status={integration.status}
          isConnecting={isConnecting}
          moderateScale={moderateScale}
          spacing={spacing}
          fontSize={fontSize}
        />
        {!isConnecting && isConnected ? (
          <Pressable
            onPress={() => onPress(integration)}
            style={({ pressed }) => ({
              borderRadius: moderateScale(12, 0.5),
              paddingHorizontal: spacing.sm + 2,
              paddingVertical: 4,
              borderWidth: 1,
              borderColor: "rgba(239,68,68,0.4)",
              backgroundColor: pressed ? "rgba(239,68,68,0.12)" : "transparent",
            })}
          >
            <Text
              style={{
                fontSize: fontSize.xs - 1,
                color: "#ef4444",
                fontWeight: "500",
              }}
            >
              Disconnect
            </Text>
          </Pressable>
        ) : !isConnecting && isAvailable && integration.status !== "created" ? (
          <Pressable
            onPress={() => onPress(integration)}
            style={({ pressed }) => ({
              borderRadius: moderateScale(12, 0.5),
              paddingHorizontal: spacing.sm + 2,
              paddingVertical: 4,
              borderWidth: 1,
              borderColor: "rgba(0,187,255,0.4)",
              backgroundColor: pressed ? "rgba(0,187,255,0.12)" : "transparent",
            })}
          >
            <Text
              style={{
                fontSize: fontSize.xs - 1,
                color: "#00bbff",
                fontWeight: "500",
              }}
            >
              Connect
            </Text>
          </Pressable>
        ) : null}
      </View>
    </Pressable>
  );
}

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
      <Text
        style={{
          fontSize: fontSize.xs,
          color: "#8e8e93",
        }}
      >
        {count}
      </Text>
    </View>
  );
}

function EmptyState({ query }: { query: string }) {
  const { spacing } = useResponsive();

  return (
    <View
      style={{ paddingHorizontal: spacing.md, paddingVertical: spacing.xl * 2 }}
    >
      <AppEmptyStateCard
        title={query ? `No results for "${query}"` : "No integrations found"}
        description={
          query ? "Try a different search term." : "Check back later."
        }
        icon={<AppIcon icon={ConnectIcon} size={40} color="#3a3a3c" />}
        className="rounded-2xl bg-[#17191f]"
        bodyClassName="px-6 py-10"
      />
    </View>
  );
}

type ListItem =
  | { type: "section-header"; category: string; count: number }
  | { type: "integration"; integration: Integration };

export function IntegrationsScreen() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { spacing, fontSize } = useResponsive();

  const createSheetRef = useRef<CreateMCPIntegrationSheetRef>(null);
  const bearerSheetRef = useRef<BearerTokenSheetRef>(null);

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
      // Silent fail - already handled in API layer.
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

  const availableCategories = useMemo(() => {
    const categories = new Set(
      integrations.map((integration) => integration.category),
    );
    const categoryOrder: Record<string, number> = {
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

    return Array.from(categories).sort(
      (left, right) =>
        (categoryOrder[left] ?? 50) - (categoryOrder[right] ?? 50),
    );
  }, [integrations]);

  const categoryOptions = useMemo(
    () => [
      { key: "all", label: "All" },
      ...availableCategories.map((category) => ({
        key: category,
        label: getCategoryLabel(category),
      })),
    ],
    [availableCategories],
  );

  const filteredIntegrations = useMemo(() => {
    let results = integrations;

    if (selectedCategory !== "all") {
      results = results.filter(
        (integration) => integration.category === selectedCategory,
      );
    }

    const normalizedQuery = searchQuery.trim().toLowerCase();
    if (normalizedQuery) {
      results = results.filter(
        (integration) =>
          integration.name.toLowerCase().includes(normalizedQuery) ||
          integration.description.toLowerCase().includes(normalizedQuery),
      );
    }

    return results;
  }, [integrations, searchQuery, selectedCategory]);

  const connectedCount = useMemo(
    () =>
      integrations.filter((integration) => integration.status === "connected")
        .length,
    [integrations],
  );

  const listItems = useMemo<ListItem[]>(() => {
    if (selectedCategory !== "all") {
      return filteredIntegrations.map((integration) => ({
        type: "integration" as const,
        integration,
      }));
    }

    const grouped: Record<string, Integration[]> = {};
    for (const integration of filteredIntegrations) {
      if (!grouped[integration.category]) {
        grouped[integration.category] = [];
      }
      grouped[integration.category].push(integration);
    }

    const items: ListItem[] = [];
    const orderedCategories = availableCategories.filter(
      (category) => grouped[category]?.length,
    );

    for (const category of orderedCategories) {
      items.push({
        type: "section-header",
        category,
        count: grouped[category].length,
      });

      for (const integration of grouped[category]) {
        items.push({ type: "integration", integration });
      }
    }

    return items;
  }, [availableCategories, filteredIntegrations, selectedCategory]);

  const handleSearchChange = useCallback(
    (text: string) => {
      setSearchQuery(text);
      if (text && selectedCategory !== "all") {
        setSelectedCategory("all");
      }
    },
    [selectedCategory],
  );

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
        return;
      }

      // Route by auth_type
      const authType = integration.authType ?? "oauth";

      if (authType === "bearer") {
        // Bearer token flow: open token input sheet
        bearerSheetRef.current?.open({
          integrationId: integration.id,
          integrationName: integration.name,
          iconUrl: integration.iconUrl,
        });
      } else if (authType === "none") {
        // Direct connect (no auth required)
        setConnectingId(integration.id);
        const result = await connectIntegration(integration.id);
        if (result.success) {
          await load();
        } else if (!result.cancelled) {
          Alert.alert("Error", result.error ?? "Failed to connect integration");
        }
        setConnectingId(null);
      } else {
        // OAuth flow (default)
        setConnectingId(integration.id);
        const result = await connectIntegration(integration.id);
        if (result.success) {
          await load();
        } else if (!result.cancelled) {
          Alert.alert("Error", result.error ?? "Failed to connect integration");
        }
        setConnectingId(null);
      }

      setConnectingId(integration.id);
      const result = await connectIntegration(integration.id);
      if (result.success) {
        await load();
      } else if (!result.cancelled) {
        Alert.alert("Error", result.error ?? "Failed to connect integration");
      }
      setConnectingId(null);
    },
    [connectingId, load],
  );

  const keyExtractor = useCallback((item: ListItem) => {
    if (item.type === "section-header") return `header-${item.category}`;
    return `integration-${item.integration.id}`;
  }, []);

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
        <View
          style={{ paddingHorizontal: spacing.md, marginBottom: spacing.sm }}
        >
          <IntegrationRow
            integration={item.integration}
            connectingId={connectingId}
            onPress={handleIntegrationPress}
          />
        </View>
      );
    },
    [connectingId, handleIntegrationPress, spacing.md, spacing.sm],
  );

  const ListHeader = useCallback(
    () => (
      <View style={{ gap: spacing.md, paddingBottom: spacing.md }}>
        <View style={{ paddingHorizontal: spacing.md }}>
          <AppSectionCard
            className="rounded-2xl bg-[#17191f]"
            bodyClassName="flex-row items-center justify-between px-4 py-3"
          >
            <Text style={{ fontSize: fontSize.xs, color: "#d4d4d8" }}>
              {connectedCount} of {integrations.length} connected
            </Text>
            {selectedCategory !== "all" ? (
              <AppStatusChip
                label={getCategoryLabel(selectedCategory)}
                tone="accent"
              />
            ) : null}
          </AppSectionCard>
        </View>

        {availableCategories.length > 0 ? (
          <ScrollView
            horizontal
            showsHorizontalScrollIndicator={false}
            contentContainerStyle={{ paddingHorizontal: spacing.md }}
          >
            <AppFilterChipGroup
              options={categoryOptions}
              selectedKey={selectedCategory}
              onSelect={(category) => {
                setSelectedCategory(category ?? "all");
              }}
              className="flex-nowrap gap-2"
              selectedVariant="primary"
              unselectedVariant="tertiary"
              chipClassName="bg-white/10"
            />
          </ScrollView>
        ) : null}
      </View>
    ),
    [
      availableCategories.length,
      categoryOptions,
      connectedCount,
      fontSize.xs,
      integrations.length,
      selectedCategory,
      spacing.md,
    ],
  );

  const ListEmpty = useCallback(
    () =>
      isLoading ? (
        <View
          style={{
            paddingHorizontal: spacing.md,
            paddingVertical: spacing.xl * 2,
          }}
        >
          <AppSectionCard
            className="rounded-2xl bg-[#17191f]"
            bodyClassName="items-center px-6 py-10"
          >
            <ActivityIndicator color="#00bbff" />
            <Text style={{ fontSize: fontSize.sm, color: "#8e8e93" }}>
              Loading integrations...
            </Text>
          </AppSectionCard>
        </View>
      ) : (
        <EmptyState query={searchQuery} />
      ),
    [fontSize.sm, isLoading, searchQuery, spacing.md, spacing.xl],
  );

  return (
    <View style={{ flex: 1, backgroundColor: "#131416" }}>
      <View
        style={{
          paddingTop: insets.top + spacing.sm,
          paddingBottom: spacing.md,
          borderBottomWidth: 1,
          borderBottomColor: "rgba(255,255,255,0.08)",
          gap: spacing.md,
        }}
      >
        <View style={{ paddingHorizontal: spacing.md }}>
          <View
            style={{
              flexDirection: "row",
              alignItems: "center",
              gap: spacing.sm,
            }}
          >
            <Pressable
              onPress={() => router.back()}
              style={{
                width: 36,
                height: 36,
                borderRadius: 18,
                backgroundColor: "rgba(255,255,255,0.06)",
                alignItems: "center",
                justifyContent: "center",
              }}
            >
              <AppIcon icon={ArrowLeft01Icon} size={18} color="#ffffff" />
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

            {/* Add custom integration button */}
            <Pressable
              onPress={() => createSheetRef.current?.open()}
              style={({ pressed }) => ({
                flexDirection: "row",
                alignItems: "center",
                gap: 5,
                paddingHorizontal: spacing.sm + 4,
                paddingVertical: 7,
                borderRadius: moderateScale(20, 0.5),
                backgroundColor: pressed
                  ? "rgba(0,170,230,0.9)"
                  : "rgba(0,187,255,0.85)",
              })}
            >
              <AppIcon icon={PlusSignIcon} size={14} color="#fff" />
              <Text
                style={{
                  fontSize: fontSize.xs,
                  fontWeight: "600",
                  color: "#fff",
                }}
              >
                Add MCP
              </Text>
            </Pressable>
          </View>
        </View>

        <View style={{ paddingHorizontal: spacing.md }}>
          <AppSearchInput
            value={searchQuery}
            onChangeText={handleSearchChange}
            placeholder="Search integrations"
            className="gap-0"
            inputClassName="bg-white/5"
          />
        </View>
      </View>

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

      {/* ─── Create MCP Integration Sheet ────────────────────────────────── */}
      <CreateMCPIntegrationSheet
        ref={createSheetRef}
        onIntegrationCreated={() => void load()}
      />

      {/* ─── Bearer Token Sheet ───────────────────────────────────────────── */}
      <BearerTokenSheet ref={bearerSheetRef} onSuccess={() => void load()} />
    </View>
  );
}
