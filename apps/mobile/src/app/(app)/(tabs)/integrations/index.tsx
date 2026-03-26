import { Image } from "expo-image";
import { Button, Card } from "heroui-native";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ActivityIndicator,
  Pressable,
  ScrollView,
  TextInput,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { AppIcon, Search01Icon } from "@/components/icons";
import { Text } from "@/components/ui/text";
import {
  connectIntegration,
  disconnectIntegration,
  fetchIntegrationsConfig,
} from "@/features/integrations/api/integrations-api";
import {
  IntegrationDetailSheet,
  type IntegrationDetailSheetRef,
} from "@/features/integrations/components/integration-detail-sheet";
import type { IntegrationWithStatus } from "@/features/integrations/types";
import { useResponsive } from "@/lib/responsive";

export default function IntegrationsPage() {
  const insets = useSafeAreaInsets();
  const { spacing, fontSize } = useResponsive();
  const [query, setQuery] = useState("");
  const [integrations, setIntegrations] = useState<IntegrationWithStatus[]>([]);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);
  const detailSheetRef = useRef<IntegrationDetailSheetRef>(null);

  const load = useCallback(async () => {
    setLoading(true);
    const data = await fetchIntegrationsConfig();
    setIntegrations(data);
    setLoading(false);
  }, []);

  useEffect(() => {
    void load();
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

  const handleToggle = useCallback(
    async (integration: IntegrationWithStatus) => {
      if (busyId) return;
      setBusyId(integration.id);
      if (integration.connected) {
        await disconnectIntegration(integration.id);
      } else {
        await connectIntegration(integration.id);
      }
      await load();
      setBusyId(null);
    },
    [busyId, load],
  );

  const handleDetailConnect = useCallback(
    async (integrationId: string, _authType?: string, _token?: string) => {
      if (busyId) return;
      setBusyId(integrationId);
      await connectIntegration(integrationId);
      await load();
      setBusyId(null);
    },
    [busyId, load],
  );

  const handleDetailDisconnect = useCallback(
    async (integrationId: string) => {
      if (busyId) return;
      setBusyId(integrationId);
      await disconnectIntegration(integrationId);
      await load();
      setBusyId(null);
    },
    [busyId, load],
  );

  return (
    <View style={{ flex: 1, backgroundColor: "#0b0c0f" }}>
      <View
        style={{
          paddingTop: insets.top + spacing.sm,
          paddingHorizontal: spacing.md,
          paddingBottom: spacing.md,
          borderBottomWidth: 1,
          borderBottomColor: "rgba(255,255,255,0.1)",
        }}
      >
        <Text
          style={{
            fontSize: fontSize.lg,
            fontWeight: "600",
            color: "#fff",
            marginBottom: spacing.md,
          }}
        >
          Integrations
        </Text>

        <View
          style={{
            flexDirection: "row",
            alignItems: "center",
            borderRadius: 12,
            backgroundColor: "rgba(255,255,255,0.05)",
            paddingHorizontal: spacing.md,
            paddingVertical: spacing.sm,
          }}
        >
          <AppIcon icon={Search01Icon} size={16} color="#90939a" />
          <TextInput
            value={query}
            onChangeText={setQuery}
            style={{
              flex: 1,
              marginLeft: spacing.sm,
              color: "#ffffff",
              fontSize: fontSize.sm,
            }}
            placeholder="Search integrations"
            placeholderTextColor="#6f737c"
          />
        </View>
      </View>

      {loading ? (
        <View
          style={{ flex: 1, alignItems: "center", justifyContent: "center" }}
        >
          <ActivityIndicator size="large" color="#b8bcc6" />
        </View>
      ) : (
        <ScrollView contentContainerStyle={{ padding: 16, gap: 10 }}>
          <Text
            style={{ fontSize: fontSize.xs, color: "#8e8e93", marginBottom: 4 }}
          >
            {connectedCount}/{filtered.length} connected
          </Text>

          {filtered.map((integration) => {
            const isBusy = integration.id === busyId;
            return (
              <Pressable
                key={integration.id}
                onPress={() => detailSheetRef.current?.open(integration)}
                style={{ opacity: isBusy ? 0.7 : 1 }}
              >
                <Card className="rounded-xl bg-[#17191f]">
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
                          integration.connected
                            ? "bg-success/15"
                            : "bg-white/10"
                        }
                        isDisabled={isBusy}
                        onPress={() => {
                          void handleToggle(integration);
                        }}
                      >
                        <Button.Label
                          className={
                            integration.connected
                              ? "text-success"
                              : "text-muted"
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
              </Pressable>
            );
          })}
        </ScrollView>
      )}

      <IntegrationDetailSheet
        ref={detailSheetRef}
        onConnect={(id, authType, token) => {
          void handleDetailConnect(id, authType, token);
        }}
        onDisconnect={(id) => {
          void handleDetailDisconnect(id);
        }}
      />
    </View>
  );
}
