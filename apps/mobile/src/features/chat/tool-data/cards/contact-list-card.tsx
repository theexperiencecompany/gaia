import { Avatar, Card, ListGroup, Separator } from "heroui-native";
import { View } from "react-native";
import {
  AppIcon,
  Call02Icon,
  Contact01Icon,
  Mail01Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";

export interface ContactData {
  name?: string;
  email?: string;
  phone?: string;
  resource_name?: string;
}

function getInitials(name?: string): string {
  if (!name) return "?";
  const parts = name.trim().split(" ");
  if (parts.length >= 2) {
    return `${parts[0][0]}${parts[parts.length - 1][0]}`.toUpperCase();
  }
  return name[0].toUpperCase();
}

function ContactItem({ contact }: { contact: ContactData }) {
  const initials = getInitials(contact.name);

  return (
    <ListGroup.Item>
      <Avatar
        alt={contact.name ?? initials}
        size="sm"
        className="bg-[#00bbff]/20"
      >
        <Avatar.Fallback className="text-[#00bbff] text-xs font-semibold">
          {initials}
        </Avatar.Fallback>
      </Avatar>
      <View className="flex-1 min-w-0">
        <ListGroup.ItemText numberOfLines={1}>
          {contact.name || contact.email || "Unknown"}
        </ListGroup.ItemText>
        <View className="flex-row flex-wrap gap-x-3 mt-0.5">
          {contact.email && (
            <View className="flex-row items-center gap-1">
              <AppIcon icon={Mail01Icon} size={11} color="#8e8e93" />
              <ListGroup.ItemDescription numberOfLines={1}>
                {contact.email}
              </ListGroup.ItemDescription>
            </View>
          )}
          {contact.phone && (
            <View className="flex-row items-center gap-1">
              <AppIcon icon={Call02Icon} size={11} color="#8e8e93" />
              <ListGroup.ItemDescription>
                {contact.phone}
              </ListGroup.ItemDescription>
            </View>
          )}
        </View>
      </View>
    </ListGroup.Item>
  );
}

export function ContactListCard({ data }: { data: ContactData[] }) {
  return (
    <Card variant="secondary" className="mx-4 my-2 rounded-2xl bg-[#171920]">
      <Card.Body className="py-3 px-4">
        <View className="flex-row items-center gap-2 mb-3">
          <AppIcon icon={Contact01Icon} size={14} color="#8e8e93" />
          <Text className="text-xs text-[#8e8e93]">Contacts</Text>
          <View className="rounded-full bg-white/10 px-2 py-0.5 ml-auto">
            <Text className="text-[10px] text-[#8e8e93]">
              {data.length} {data.length === 1 ? "contact" : "contacts"}
            </Text>
          </View>
        </View>
        <ListGroup className="rounded-xl bg-white/5 border border-white/8 overflow-hidden">
          {data.map((contact, index) => (
            <View key={contact.email || contact.resource_name || String(index)}>
              {index > 0 && <Separator />}
              <ContactItem contact={contact} />
            </View>
          ))}
        </ListGroup>
      </Card.Body>
    </Card>
  );
}
