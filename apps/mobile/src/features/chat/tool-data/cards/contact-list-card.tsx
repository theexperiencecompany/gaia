import { Avatar, Card } from "heroui-native";
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
    <View
      style={{
        flexDirection: "row",
        alignItems: "center",
        padding: 12,
        gap: 10,
      }}
    >
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
        <Text
          style={{ fontSize: 14, color: "#e4e4e7", fontWeight: "500" }}
          numberOfLines={1}
        >
          {contact.name || contact.email || "Unknown"}
        </Text>
        <View className="flex-row flex-wrap gap-x-3 mt-0.5">
          {contact.email && (
            <View className="flex-row items-center gap-1">
              <AppIcon icon={Mail01Icon} size={11} color="#8e8e93" />
              <Text
                style={{ fontSize: 12, color: "#8e8e93" }}
                numberOfLines={1}
              >
                {contact.email}
              </Text>
            </View>
          )}
          {contact.phone && (
            <View className="flex-row items-center gap-1">
              <AppIcon icon={Call02Icon} size={11} color="#8e8e93" />
              <Text style={{ fontSize: 12, color: "#8e8e93" }}>
                {contact.phone}
              </Text>
            </View>
          )}
        </View>
      </View>
    </View>
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
        <View className="rounded-xl bg-white/5 border border-white/8 overflow-hidden">
          {data.map((contact, index) => (
            <View key={contact.email || contact.resource_name || String(index)}>
              {index > 0 && (
                <View
                  style={{
                    height: 1,
                    backgroundColor: "rgba(255,255,255,0.07)",
                    marginVertical: 4,
                  }}
                />
              )}
              <ContactItem contact={contact} />
            </View>
          ))}
        </View>
      </Card.Body>
    </Card>
  );
}
