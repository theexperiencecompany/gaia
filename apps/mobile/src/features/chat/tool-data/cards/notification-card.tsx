import { Card } from "heroui-native";
import { Text } from "@/components/ui/text";

export interface NotificationData {
  notifications?: Array<{
    title?: string;
    body?: string;
    type?: string;
  }>;
}

export function NotificationCard({ data }: { data: NotificationData }) {
  const count = data.notifications?.length || 0;

  return (
    <Card variant="secondary" className="mx-4 my-2 rounded-xl">
      <Card.Body className="p-4">
        <Text className="text-xs text-muted mb-1">Notifications</Text>
        <Text className="text-foreground text-sm">
          {count} notification{count !== 1 ? "s" : ""}
        </Text>
        {data.notifications?.slice(0, 2).map((notif) => (
          <Text
            key={notif.title || notif.body}
            className="text-muted text-xs mt-1"
            numberOfLines={1}
          >
            • {notif.title || notif.body}
          </Text>
        ))}
      </Card.Body>
    </Card>
  );
}
