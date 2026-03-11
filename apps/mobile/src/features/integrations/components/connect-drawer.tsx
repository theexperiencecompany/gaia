import {
  BottomSheetBackdrop,
  type BottomSheetBackdropProps,
  BottomSheetFlatList,
  BottomSheetModal,
} from "@gorhom/bottom-sheet";
import { Image } from "expo-image";
import { Button, Chip } from "heroui-native";
import {
  forwardRef,
  useCallback,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  ActivityIndicator,
  Alert,
  Pressable,
  ScrollView,
  TextInput,
  View,
} from "react-native";
import {
  Cancel01Icon,
  AppIcon,
  Search01Icon,
  Wrench01Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
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
  github:
    "https://upload.wikimedia.org/wikipedia/commons/thumb/c/c2/GitHub_Invertocat_Logo.svg/512px-GitHub_Invertocat_Logo.svg.png",
  slack:
    "https://upload.wikimedia.org/wikipedia/commons/thumb/d/d5/Slack_icon_2019.svg/512px-Slack_icon_2019.svg.png",
  todoist:
    "https://upload.wikimedia.org/wikipedia/commons/thumb/6/6d/Todoist_logo.svg/512px-Todoist_logo.svg.png",
  linear:
    "https://upload.wikimedia.org/wikipedia/commons/thumb/5/59/Linear_logo.svg/512px-Linear_logo.svg.png",
};

function getLogoUri(integration: Integration): string {
  if (integration.iconUrl) return integration.iconUrl;
  return (
    INTEGRATION_LOGOS[integration.id] ||
    "https://upload.wikimedia.org/wikipedia/commons/thumb/a/ac/No_image_available.svg/512px-No_image_available.svg.png"
  );
}

export interface ConnectDrawerRef {
  open: () => void;
  close: () => void;
}

interface ConnectDrawerProps {
  onOpen?: () => void;
}

export const ConnectDrawer = forwardRef<ConnectDrawerRef, ConnectDrawerProps>(
  ({ onOpen }, ref) => {
    const bottomSheetRef = useRef<BottomSheetModal>(null);
    const [searchQuery, setSearchQuery] = useState("");
    const [selectedFilter, setSelectedFilter] = useState("all");
    const [integrations, setIntegrations] = useState<Integration[]>([]);
    const [isLoading, setIsLoading] = useState(false);
    const [hasLoaded, setHasLoaded] = useState(false);
    const [connectingId, setConnectingId] = useState<string | null>(null);

    const snapPoints = useMemo(() => ["75%"], []);

    useImperativeHandle(ref, () => ({
      open: () => {
        onOpen?.();
        bottomSheetRef.current?.present();
        loadIntegrations();
      },
      close: () => {
        bottomSheetRef.current?.dismiss();
      },
    }));

    const loadIntegrations = async () => {
      if (hasLoaded) return;
      setIsLoading(true);
      try {
        const data = await fetchIntegrations();
        setIntegrations(data);
        setHasLoaded(true);
      } catch (error) {
        console.error("Failed to load integrations:", error);
      } finally {
        setIsLoading(false);
      }
    };

    const refreshIntegrations = async () => {
      try {
        const data = await fetchIntegrations();
        setIntegrations(data);
      } catch (error) {
        console.error("Failed to refresh integrations:", error);
      }
    };

    // Derive available categories from data
    const availableCategories = useMemo(() => {
      const cats = new Set(integrations.map((i) => i.category));
      return ["all", ...Array.from(cats)];
    }, [integrations]);

    const filteredIntegrations = useMemo(() => {
      let results = integrations;

      if (selectedFilter !== "all") {
        results = results.filter((i) => i.category === selectedFilter);
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
    }, [integrations, selectedFilter, searchQuery]);

    const connectedCount = useMemo(
      () => filteredIntegrations.filter((i) => i.status === "connected").length,
      [filteredIntegrations],
    );

    const handleConnect = async (integration: Integration) => {
      if (connectingId) return;

      if (integration.status === "connected") {
        setConnectingId(integration.id);
        const success = await disconnectIntegration(integration.id);
        if (success) {
          await refreshIntegrations();
        } else {
          Alert.alert("Error", "Failed to disconnect integration");
        }
        setConnectingId(null);
      } else {
        setConnectingId(integration.id);
        const result = await connectIntegration(integration.id);
        if (result.success) {
          await refreshIntegrations();
        } else if (!result.cancelled) {
          Alert.alert("Error", result.error || "Failed to connect integration");
        }
        setConnectingId(null);
      }
    };

    const renderBackdrop = useCallback(
      (props: BottomSheetBackdropProps) => (
        <BottomSheetBackdrop
          {...props}
          disappearsOnIndex={-1}
          appearsOnIndex={0}
          opacity={0.5}
        />
      ),
      [],
    );

    const renderItem = useCallback(
      ({ item: integration }: { item: Integration }) => {
        const isConnecting = connectingId === integration.id;
        const isConnected = integration.status === "connected";
        const isAvailable =
          integration.source === "custom" || integration.available !== false;

        return (
          <Pressable
            onPress={() => handleConnect(integration)}
            className="flex-row items-center px-4 py-3 active:opacity-60"
            disabled={isConnecting}
          >
            <View className="w-9 h-9 rounded-lg items-center justify-center mr-3">
              <Image
                source={{ uri: getLogoUri(integration) }}
                style={{ width: 28, height: 28 }}
                contentFit="contain"
              />
            </View>

            <View className="flex-1 mr-3">
              <View className="flex-row items-center gap-1.5">
                <Text className="font-medium text-sm">{integration.name}</Text>
                {isConnected && (
                  <View className="h-2 w-2 rounded-full bg-success" />
                )}
                {integration.status === "created" && (
                  <View className="h-2 w-2 rounded-full bg-warning" />
                )}
              </View>
              <Text className="text-muted text-xs" numberOfLines={1}>
                {integration.description}
              </Text>
            </View>

            {isConnected ? (
              <Button
                size="sm"
                variant="tertiary"
                onPress={() => handleConnect(integration)}
                isDisabled={isConnecting}
                className="bg-success/15 px-3 min-w-[90px]"
              >
                {isConnecting ? (
                  <ActivityIndicator size="small" color="#8e8e93" />
                ) : (
                  <Button.Label className="text-success text-xs">
                    Connected
                  </Button.Label>
                )}
              </Button>
            ) : isAvailable ? (
              <Button
                size="sm"
                variant="tertiary"
                onPress={() => handleConnect(integration)}
                isDisabled={isConnecting}
                className="bg-primary/15 px-3 min-w-[90px]"
              >
                {isConnecting ? (
                  <ActivityIndicator size="small" color="#8e8e93" />
                ) : (
                  <Button.Label className="text-primary text-xs">
                    Connect
                  </Button.Label>
                )}
              </Button>
            ) : null}
          </Pressable>
        );
      },
      [connectingId],
    );

    const ListHeader = useCallback(
      () => (
        <View className="flex-row items-center justify-between px-4 py-2">
          <Text className="text-sm font-medium text-zinc-400">
            {selectedFilter === "all"
              ? "All Integrations"
              : getCategoryLabel(selectedFilter)}
          </Text>
          <Text className="text-sm text-muted">
            {connectedCount}/{filteredIntegrations.length} connected
          </Text>
        </View>
      ),
      [filteredIntegrations, connectedCount, selectedFilter],
    );

    const ListEmpty = useCallback(
      () =>
        isLoading ? (
          <View className="items-center justify-center py-8">
            <ActivityIndicator size="large" color="#8e8e93" />
            <Text className="text-muted text-sm mt-2">
              Loading integrations...
            </Text>
          </View>
        ) : (
          <View className="items-center justify-center py-8">
            <Text className="text-muted text-sm">
              {searchQuery
                ? `No integrations found for "${searchQuery}"`
                : "No integrations available"}
            </Text>
          </View>
        ),
      [isLoading, searchQuery],
    );

    return (
      <BottomSheetModal
        ref={bottomSheetRef}
        snapPoints={snapPoints}
        enableDynamicSizing={false}
        enablePanDownToClose
        backdropComponent={renderBackdrop}
        backgroundStyle={{ backgroundColor: "#0b0c0f" }}
        handleIndicatorStyle={{ backgroundColor: "#3a3a3c", width: 40 }}
      >
        {/* Header */}
        <View className="flex-row items-center justify-between px-4 pb-3">
          <Text className="text-lg font-semibold">Integrations</Text>
          <Pressable
            onPress={() => bottomSheetRef.current?.dismiss()}
            className="w-8 h-8 rounded-full bg-white/5 items-center justify-center active:opacity-60"
          >
            <AppIcon icon={Cancel01Icon} size={18} color="#8e8e93" />
          </Pressable>
        </View>

        {/* Search */}
        <View className="px-4 pb-2">
          <View className="flex-row items-center rounded-xl px-3 py-2.5 bg-white/5">
            <AppIcon icon={Search01Icon} size={16} color="#6f737c" />
            <TextInput
              className="flex-1 ml-2 text-white text-sm"
              placeholder="Search integrations..."
              placeholderTextColor="#6f737c"
              value={searchQuery}
              onChangeText={setSearchQuery}
            />
          </View>
        </View>

        {/* Category Filter Chips */}
        <ScrollView
          horizontal
          showsHorizontalScrollIndicator={false}
          className="px-4 py-3"
          contentContainerStyle={{ gap: 8 }}
        >
          {availableCategories.map((category) => (
            <Chip
              key={category}
              variant={selectedFilter === category ? "primary" : "secondary"}
              color={selectedFilter === category ? "accent" : "default"}
              onPress={() => setSelectedFilter(category)}
            >
              <Chip.Label>{getCategoryLabel(category)}</Chip.Label>
            </Chip>
          ))}
        </ScrollView>

        {/* Integration List */}
        <BottomSheetFlatList
          data={filteredIntegrations}
          keyExtractor={(item: Integration) => item.id}
          renderItem={renderItem}
          ListHeaderComponent={ListHeader}
          ListEmptyComponent={ListEmpty}
          contentContainerStyle={{ paddingBottom: 24 }}
          showsVerticalScrollIndicator={false}
        />
      </BottomSheetModal>
    );
  },
);

ConnectDrawer.displayName = "ConnectDrawer";

interface ConnectDrawerTriggerProps {
  onOpen?: () => void;
}

export function ConnectDrawerTrigger({ onOpen }: ConnectDrawerTriggerProps) {
  const drawerRef = useRef<ConnectDrawerRef>(null);

  const handleOpen = () => {
    drawerRef.current?.open();
  };

  return (
    <>
      <Button
        variant="tertiary"
        isIconOnly
        size="sm"
        className="rounded-full"
        onPress={handleOpen}
      >
        <AppIcon icon={Wrench01Icon} size={18} color="#8e8e93" />
      </Button>

      <ConnectDrawer ref={drawerRef} onOpen={onOpen} />
    </>
  );
}
