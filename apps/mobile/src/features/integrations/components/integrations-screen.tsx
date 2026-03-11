import { Image } from "expo-image";
import { useFocusEffect, useRouter } from "expo-router";
import { Button, Spinner } from "heroui-native";
import { useCallback, useMemo, useState } from "react";
import {
  Alert,
  FlatList,
  RefreshControl,
  ScrollView,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { AppIcon, ArrowLeft01Icon, ConnectIcon } from "@/components/icons";
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

function getLogoUri(integration: Integration): string {
  if (integration.iconUrl) return integration.iconUrl;
  return (
    INTEGRATION_LOGOS[integration.id] ??
    "https://upload.wikimedia.org/wikipedia/commons/thumb/a/ac/No_image_available.svg/512px-No_image_available.svg.png"
  );
}

interface IntegrationRowProps {
  integration: Integration;
  connectingId: string | null;
  onPress: (integration: Integration) => Promise<void>;
}

function IntegrationRow({
  integration,
  connectingId,
  onPress,
}: IntegrationRowProps) {
  const { fontSize, spacing } = useResponsive();
  const isConnected = integration.status === "connected";
  const isPending = integration.status === "created";
  const isConnecting = connectingId === integration.id;
  const isAvailable =
    integration.source === "custom" || integration.available !== false;

  const statusChip = isConnected ? (
    <AppStatusChip status="connected" />
  ) : isPending ? (
    <AppStatusChip status="pending" />
  ) : !isAvailable ? (
    <AppStatusChip label="Unavailable" tone="default" variant="secondary" />
  ) : null;

  const actionLabel = isConnected
    ? "Disconnect"
    : isPending
      ? "Continue"
      : "Connect";
  const actionClassName = isConnected
    ? "bg-danger/15"
    : isPending
      ? "bg-warning/15"
      : "bg-primary/15";
  const actionLabelClassName = isConnected
    ? "text-danger"
    : isPending
      ? "text-warning"
      : "text-primary";

  return (
    <AppSectionCard
      className="rounded-2xl bg-[#17191f]"
      bodyClassName="px-4 py-4"
    >
      <View
        style={{ flexDirection: "row", alignItems: "center", gap: spacing.md }}
      >
        <View
          style={{
            width: 44,
            height: 44,
            borderRadius: 14,
            backgroundColor: "rgba(255,255,255,0.06)",
            alignItems: "center",
            justifyContent: "center",
            flexShrink: 0,
          }}
        >
          <Image
            source={{ uri: getLogoUri(integration) }}
            style={{ width: 28, height: 28 }}
            contentFit="contain"
          />
        </View>

        <View style={{ flex: 1, minWidth: 0, gap: 4 }}>
          <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
            <Text
              style={{
                flexShrink: 1,
                fontSize: fontSize.sm,
                fontWeight: "600",
                color: "#f4f4f5",
              }}
              numberOfLines={1}
            >
              {integration.name}
            </Text>
            {statusChip}
          </View>
          <Text
            style={{
              fontSize: fontSize.xs,
              color: "#8e8e93",
            }}
            numberOfLines={2}
          >
            {integration.description}
          </Text>
        </View>

        {isAvailable ? (
          <Button
            size="sm"
            variant="tertiary"
            className={actionClassName}
            isDisabled={isConnecting}
            onPress={() => {
              void onPress(integration);
            }}
          >
            {isConnecting ? (
              <Spinner size="sm" />
            ) : (
              <Button.Label className={actionLabelClassName}>
                {actionLabel}
              </Button.Label>
            )}
          </Button>
        ) : null}
      </View>
    </AppSectionCard>
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
            <Spinner />
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
            <Button
              isIconOnly
              variant="secondary"
              size="sm"
              onPress={() => router.back()}
            >
              <AppIcon icon={ArrowLeft01Icon} size={18} color="#ffffff" />
            </Button>

            <View style={{ flex: 1 }}>
              <Text
                style={{
                  fontSize: fontSize.base,
                  fontWeight: "600",
                  color: "#ffffff",
                }}
              >
                Integrations
              </Text>
              <Text
                style={{
                  fontSize: fontSize.xs,
                  color: "#8e8e93",
                  marginTop: 2,
                }}
              >
                Connect the tools your workflows can use.
              </Text>
            </View>
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
    </View>
  );
}
