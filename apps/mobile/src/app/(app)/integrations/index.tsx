import { Image } from "expo-image";
import { useRouter } from "expo-router";
import { Button, Card } from "heroui-native";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ActivityIndicator,
  Pressable,
  ScrollView,
  TextInput,
  View,
} from "react-native";
import {
  ArrowLeft01Icon,
  HugeiconsIcon,
  Search01Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import type { IntegrationWithStatus } from "@/features/integrations";
import {
  connectIntegration,
  disconnectIntegration,
  fetchIntegrationsConfig,
} from "@/features/integrations";

export default function IntegrationsPage() {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [integrations, setIntegrations] = useState<IntegrationWithStatus[]>([]);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    const data = await fetchIntegrationsConfig();
    setIntegrations(data);
    setLoading(false);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return integrations;
    return integrations.filter(
      (item) =>
        item.name.toLowerCase().includes(q) ||
        item.description.toLowerCase().includes(q),
    );
  }, [integrations, query]);

  const connectedCount = useMemo(
    () => filtered.filter((item) => item.connected).length,
    [filtered],
  );

  const handleToggle = async (integration: IntegrationWithStatus) => {
    if (busyId) return;

    setBusyId(integration.id);
    if (integration.connected) {
      await disconnectIntegration(integration.id);
    } else {
      await connectIntegration(integration.id);
    }
    await load();
    setBusyId(null);
  };

  return (
    <View className="flex-1 bg-[#0b0c0f]">
      <View className="px-4 pt-14 pb-4 border-b border-white/10">
        <View className="flex-row items-center justify-between mb-3">
          <Pressable
            onPress={() => router.back()}
            className="h-9 w-9 rounded-full items-center justify-center bg-white/5"
          >
            <HugeiconsIcon icon={ArrowLeft01Icon} size={18} color="#fff" />
          </Pressable>
          <Text className="text-base font-semibold">Integrations</Text>
          <View className="h-9 w-9" />
        </View>

        <View className="flex-row items-center rounded-xl bg-white/5 px-3 py-2">
          <HugeiconsIcon icon={Search01Icon} size={16} color="#90939a" />
          <TextInput
            value={query}
            onChangeText={setQuery}
            className="ml-2 flex-1 text-white"
            placeholder="Search integrations"
            placeholderTextColor="#6f737c"
          />
        </View>
      </View>

      {loading ? (
        <View className="flex-1 items-center justify-center">
          <ActivityIndicator size="large" color="#b8bcc6" />
        </View>
      ) : (
        <ScrollView contentContainerStyle={{ padding: 16, gap: 10 }}>
          <Text className="text-xs text-muted mb-1">
            {connectedCount}/{filtered.length} connected
          </Text>

          {filtered.map((integration) => {
            const isBusy = integration.id === busyId;
            return (
              <Card key={integration.id} className="rounded-xl bg-[#17191f]">
                <Card.Body className="px-3 py-3">
                  <View className="flex-row items-center gap-3">
                    <Image
                      source={{ uri: integration.logo }}
                      style={{ width: 30, height: 30 }}
                      contentFit="contain"
                    />
                    <View className="flex-1">
                      <Text className="text-sm font-medium">
                        {integration.name}
                      </Text>
                      <Text className="text-xs text-muted" numberOfLines={2}>
                        {integration.description}
                      </Text>
                    </View>
                    <Button
                      size="sm"
                      variant="tertiary"
                      className={
                        integration.connected ? "bg-success/15" : "bg-white/10"
                      }
                      isDisabled={isBusy}
                      onPress={() => handleToggle(integration)}
                    >
                      <Button.Label
                        className={
                          integration.connected ? "text-success" : "text-muted"
                        }
                      >
                        {isBusy
                          ? "Working..."
                          : integration.connected
                            ? "Connected"
                            : "Connect"}
                      </Button.Label>
                    </Button>
                  </View>
                </Card.Body>
              </Card>
            );
          })}
        </ScrollView>
      )}
    </View>
  );
}
