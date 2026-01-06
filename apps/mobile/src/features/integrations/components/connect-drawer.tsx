import { BottomSheetFlatList, BottomSheetView } from "@gorhom/bottom-sheet";
import { Image } from "expo-image";
import { Button, Chip, Popover, type PopoverTriggerRef } from "heroui-native";
import { useCallback, useRef, useState } from "react";
import {
  ActivityIndicator,
  Pressable,
  ScrollView,
  TextInput,
  View,
} from "react-native";
import { HugeiconsIcon, Search01Icon, Wrench01Icon } from "@/components/icons";
import { Text } from "@/components/ui/text";
import { fetchIntegrationsConfig } from "../api";
import type { IntegrationWithStatus } from "../types";

const FILTER_OPTIONS = [
  "All",
  "Featured",
  "Productivity",
  "Communication",
  "Social",
];

interface ConnectDrawerProps {
  onOpen?: () => void;
}

export function ConnectDrawer({ onOpen }: ConnectDrawerProps) {
  const popoverRef = useRef<PopoverTriggerRef>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedFilter, setSelectedFilter] = useState("All");
  const [integrations, setIntegrations] = useState<IntegrationWithStatus[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [hasLoaded, setHasLoaded] = useState(false);

  const loadIntegrations = async () => {
    if (hasLoaded) return;

    setIsLoading(true);
    try {
      const data = await fetchIntegrationsConfig();
      setIntegrations(data);
      setHasLoaded(true);
    } catch (error) {
      console.error("Failed to load integrations:", error);
    } finally {
      setIsLoading(false);
    }
  };

  const handleOpen = () => {
    onOpen?.();
    popoverRef.current?.open();
    loadIntegrations();
  };

  const filteredIntegrations = integrations.filter((integration) => {
    const matchesSearch = integration.name
      .toLowerCase()
      .includes(searchQuery.toLowerCase());

    let matchesFilter = true;
    if (selectedFilter === "Featured") {
      matchesFilter = integration.isFeatured;
    } else if (selectedFilter !== "All") {
      matchesFilter =
        integration.category.toLowerCase() === selectedFilter.toLowerCase();
    }

    return matchesSearch && matchesFilter;
  });

  const handleConnect = (id: string) => {
    setIntegrations((prev) =>
      prev.map((integration) =>
        integration.id === id
          ? { ...integration, connected: !integration.connected }
          : integration
      )
    );
  };

  const renderItem = useCallback(
    ({ item: integration }: { item: IntegrationWithStatus }) => (
      <Pressable
        onPress={() => handleConnect(integration.id)}
        className="flex-row items-center px-4 py-3 active:bg-muted/10"
      >
        <View className="w-9 h-9 rounded-lg items-center justify-center mr-3">
          <Image
            source={{ uri: integration.logo }}
            style={{ width: 28, height: 28 }}
            contentFit="contain"
          />
        </View>

        <View className="flex-1 mr-3">
          <Text className="font-medium text-sm">{integration.name}</Text>
          <Text className="text-muted text-xs" numberOfLines={1}>
            {integration.description}
          </Text>
        </View>

        <Button
          size="sm"
          variant="tertiary"
          onPress={() => handleConnect(integration.id)}
          className={
            integration.connected
              ? "bg-success/15 px-3 min-w-22.5"
              : "bg-muted/10 px-3 min-w-22.5"
          }
        >
          <Button.Label
            className={
              integration.connected
                ? "text-success text-xs"
                : "text-muted text-xs"
            }
          >
            {integration.connected ? "Connected" : "Connect"}
          </Button.Label>
        </Button>
      </Pressable>
    ),
    []
  );

  const ListHeader = useCallback(
    () => (
      <>
        <View className="flex-row items-center px-4 py-2">
          <View className="flex-1 flex-row items-center rounded-xl px-3 py-2 bg-muted/10">
            <HugeiconsIcon icon={Search01Icon} size={18} color="#8e8e93" />
            <TextInput
              className="flex-1 ml-2 text-foreground text-sm"
              placeholder="Search tools..."
              placeholderTextColor="#6b6b6b"
              value={searchQuery}
              onChangeText={setSearchQuery}
            />
          </View>
        </View>

        <ScrollView
          horizontal
          showsHorizontalScrollIndicator={false}
          className="px-4 py-2"
          contentContainerStyle={{ gap: 8 }}
        >
          {FILTER_OPTIONS.map((filter) => (
            <Chip
              key={filter}
              variant={selectedFilter === filter ? "primary" : "secondary"}
              color={selectedFilter === filter ? "accent" : "default"}
              onPress={() => setSelectedFilter(filter)}
            >
              <Chip.Label>{filter}</Chip.Label>
            </Chip>
          ))}
        </ScrollView>

        <View className="flex-row items-center justify-between px-4 py-2">
          <Text className="text-sm font-medium">Available Integrations</Text>
          <Text className="text-sm text-muted">
            {filteredIntegrations.filter((i) => i.connected).length}/
            {filteredIntegrations.length}
          </Text>
        </View>
      </>
    ),
    [searchQuery, selectedFilter, filteredIntegrations]
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
      ) : null,
    [isLoading]
  );

  return (
    <Popover>
      <Popover.Trigger ref={popoverRef} asChild={false}>
        <Button
          variant="tertiary"
          isIconOnly
          size="sm"
          className="rounded-full"
          onPress={handleOpen}
        >
          <HugeiconsIcon icon={Wrench01Icon} size={18} color="#8e8e93" />
        </Button>
      </Popover.Trigger>

      <Popover.Portal>
        <Popover.Overlay />

        <Popover.Content
          presentation="bottom-sheet"
          snapPoints={["70%"]}
          enableDynamicSizing={false}
        >
          <BottomSheetView style={{ flex: 1 }}>
            <View className="flex-row items-center justify-between px-4 pb-4">
              <Popover.Title>Connect Tools</Popover.Title>
              <Popover.Close />
            </View>

            <BottomSheetFlatList
              data={filteredIntegrations}
              keyExtractor={(item: IntegrationWithStatus) => item.id}
              renderItem={renderItem}
              ListHeaderComponent={ListHeader}
              ListEmptyComponent={ListEmpty}
              contentContainerStyle={{ paddingBottom: 24 }}
              showsVerticalScrollIndicator
            />
          </BottomSheetView>
        </Popover.Content>
      </Popover.Portal>
    </Popover>
  );
}
