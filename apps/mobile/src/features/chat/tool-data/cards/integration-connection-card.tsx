import { Button, Card } from "heroui-native";
import { Linking } from "react-native";
import { Text } from "@/components/ui/text";

export interface IntegrationConnectionData {
  integration_name?: string;
  message?: string;
  connect_url?: string;
}

export function IntegrationConnectionCard({
  data,
}: {
  data: IntegrationConnectionData;
}) {
  return (
    <Card variant="secondary" className="mx-4 my-2 rounded-xl">
      <Card.Body className="p-4">
        <Text className="text-xs text-muted mb-1">Connection Required</Text>
        <Text className="text-foreground font-medium">
          {data.integration_name || "Integration"}
        </Text>
        {data.message && (
          <Text className="text-muted text-sm mt-1">{data.message}</Text>
        )}
        {data.connect_url && (
          <Button
            variant="primary"
            size="sm"
            className="mt-2"
            onPress={() => Linking.openURL(data.connect_url!)}
          >
            <Button.Label>Connect</Button.Label>
          </Button>
        )}
      </Card.Body>
    </Card>
  );
}
