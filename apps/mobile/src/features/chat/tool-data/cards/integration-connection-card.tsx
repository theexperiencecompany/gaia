import { Button, Card } from "heroui-native";
import { Linking, View } from "react-native";
import { AlertCircleIcon, ConnectIcon } from "@/components/icons";
import { AppIcon } from "@/components/icons/app-icon";
import { Text } from "@/components/ui/text";
import { getToolCategoryIcon } from "@/features/chat/utils/tool-icons";

export interface IntegrationConnectionData {
  // API sends integration_id; integration_name is a fallback for older payloads
  integration_id?: string;
  integration_name?: string;
  message?: string;
  connect_url?: string;
}

function formatIntegrationName(id?: string): string {
  if (!id) return "Integration";
  return id.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export function IntegrationConnectionCard({
  data,
}: {
  data: IntegrationConnectionData;
}) {
  const integrationId = data.integration_id ?? data.integration_name ?? "";
  const displayName =
    data.integration_name ?? formatIntegrationName(data.integration_id);

  const icon = integrationId
    ? getToolCategoryIcon(integrationId, {
        size: 20,
        showBackground: false,
      })
    : null;

  return (
    <Card variant="secondary" className="mx-4 my-2 rounded-2xl bg-[#171920]">
      <Card.Body className="py-3 px-4">
        {/* Header: icon + name + "Not Connected" label */}
        <View className="flex-row items-start gap-3 mb-3">
          <View className="w-9 h-9 rounded-xl bg-white/5 items-center justify-center shrink-0">
            {icon ?? <AppIcon icon={ConnectIcon} size={18} color="#a1a1aa" />}
          </View>

          <View className="flex-1">
            <View className="flex-row items-center gap-2 flex-wrap">
              <Text className="text-sm font-semibold text-foreground">
                {displayName}
              </Text>
              <View className="rounded-full bg-yellow-500/10 px-2 py-0.5">
                <Text className="text-xs text-yellow-500">Not Connected</Text>
              </View>
            </View>
            <Text className="text-xs text-muted mt-0.5">
              Connection Required
            </Text>
          </View>
        </View>

        {/* Warning message */}
        {data.message && (
          <View className="flex-row items-start gap-2 rounded-xl bg-yellow-500/5 border border-yellow-500/15 p-3 mb-3">
            <AppIcon icon={AlertCircleIcon} size={14} color="#eab308" />
            <Text className="text-xs text-yellow-500/90 flex-1 leading-relaxed">
              {data.message}
            </Text>
          </View>
        )}

        {/* Connect button */}
        {data.connect_url && (
          <Button
            variant="primary"
            size="sm"
            className="w-full"
            onPress={() => Linking.openURL(data.connect_url!)}
          >
            <Button.Label>Connect {displayName}</Button.Label>
          </Button>
        )}

        {/* No URL fallback */}
        {!data.connect_url && (
          <View className="rounded-xl bg-white/5 p-3">
            <Text className="text-xs text-muted text-center">
              Open GAIA settings to connect {displayName}
            </Text>
          </View>
        )}
      </Card.Body>
    </Card>
  );
}
