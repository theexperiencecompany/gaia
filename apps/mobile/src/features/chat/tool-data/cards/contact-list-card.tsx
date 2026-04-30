import { Pressable, View } from "react-native";
import {
  AppIcon,
  Call02Icon,
  Contact01Icon,
  Mail01Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import {
  ToolCardHeader,
  ToolCardInner,
  ToolCardShell,
} from "../primitives";

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

function ContactAvatar({ name }: { name?: string }) {
  return (
    <View className="h-9 w-9 rounded-full bg-zinc-700 items-center justify-center">
      <Text className="text-zinc-100 text-xs font-semibold">
        {getInitials(name)}
      </Text>
    </View>
  );
}

function ContactRow({ contact }: { contact: ContactData }) {
  return (
    <Pressable
      className="flex-row items-center gap-3 py-2"
      android_ripple={{ color: "rgba(255,255,255,0.05)" }}
    >
      <ContactAvatar name={contact.name} />
      <View className="flex-1 min-w-0">
        <Text
          className="text-sm font-medium text-zinc-100"
          numberOfLines={1}
        >
          {contact.name || contact.email || "Unknown"}
        </Text>
        <View className="flex-row flex-wrap gap-x-3 mt-0.5">
          {contact.email && (
            <View className="flex-row items-center gap-1">
              <AppIcon icon={Mail01Icon} size={11} color="#a1a1aa" />
              <Text
                className="text-xs text-zinc-400"
                numberOfLines={1}
              >
                {contact.email}
              </Text>
            </View>
          )}
          {contact.phone && (
            <View className="flex-row items-center gap-1">
              <AppIcon icon={Call02Icon} size={11} color="#a1a1aa" />
              <Text className="text-xs text-zinc-400" numberOfLines={1}>
                {contact.phone}
              </Text>
            </View>
          )}
        </View>
      </View>
    </Pressable>
  );
}

export function ContactListCard({ data }: { data: ContactData[] }) {
  if (!data || data.length === 0) return null;

  return (
    <ToolCardShell>
      <ToolCardHeader
        icon={Contact01Icon}
        title="Contacts"
        count={data.length}
      />
      <ToolCardInner>
        {data.map((contact, index) => (
          <View
            key={contact.email || contact.resource_name || String(index)}
            className={index > 0 ? "mt-1" : ""}
          >
            <ContactRow contact={contact} />
          </View>
        ))}
      </ToolCardInner>
    </ToolCardShell>
  );
}
