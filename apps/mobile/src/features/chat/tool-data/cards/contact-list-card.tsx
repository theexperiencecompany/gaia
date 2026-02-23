import { Card } from "heroui-native";
import { View } from "react-native";
import { Text } from "@/components/ui/text";

export interface ContactData {
  name?: string;
  email?: string;
  phone?: string;
}

export function ContactListCard({ data }: { data: ContactData[] }) {
  return (
    <Card variant="secondary" className="mx-4 my-2 rounded-xl">
      <Card.Body className="p-4">
        <Text className="text-xs text-muted mb-2">
          Contacts ({data.length})
        </Text>
        {data.slice(0, 3).map((contact) => (
          <View key={contact.email || contact.name} className="mb-2 last:mb-0">
            <Text className="text-foreground text-sm">
              {contact.name || contact.email || "Unknown"}
            </Text>
            {contact.email && (
              <Text className="text-muted text-xs">{contact.email}</Text>
            )}
          </View>
        ))}
        {data.length > 3 && (
          <Text className="text-muted text-xs">+{data.length - 3} more</Text>
        )}
      </Card.Body>
    </Card>
  );
}
