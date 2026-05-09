import { ScrollView, View } from "react-native";
import {
  AppIcon,
  Call02Icon,
  Contact01Icon,
  Mail01Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { CollapsibleCard } from "@/features/chat/tool-data/primitives";

export interface ContactData {
  name?: string;
  email?: string;
  phone?: string;
  resource_name?: string;
}

function ContactRow({ contact }: { contact: ContactData }) {
  return (
    <View className="flex-row items-start gap-4 p-3">
      {/* Name Column — matches web's w-40 fixed */}
      <View className="w-40 shrink-0">
        <Text className="text-sm font-medium text-zinc-200" numberOfLines={1}>
          {contact.name}
        </Text>
      </View>

      {/* Details Column — email + phone stacked with icons */}
      <View className="flex-1 min-w-0 gap-1">
        {!!contact.email && (
          <View className="flex-row items-center gap-2">
            <AppIcon icon={Mail01Icon} size={14} color="#9ca3af" />
            <Text className="flex-1 text-sm text-zinc-400" numberOfLines={1}>
              {contact.email}
            </Text>
          </View>
        )}
        {!!contact.phone && (
          <View className="flex-row items-center gap-2">
            <AppIcon icon={Call02Icon} size={14} color="#9ca3af" />
            <Text className="text-sm text-zinc-400">{contact.phone}</Text>
          </View>
        )}
      </View>
    </View>
  );
}

export function ContactListCard({ data }: { data: ContactData[] }) {
  const count = data.length;
  const plural = count === 1 ? "" : "s";

  return (
    <CollapsibleCard
      icon={Contact01Icon}
      iconSize={20}
      title={(open) => `${open ? "Hide" : "Show"} ${count} Contact${plural}`}
      titleTone="muted"
      radius="3xl"
    >
      {count > 0 ? (
        <View className="rounded-3xl bg-zinc-800 p-3">
          <ScrollView
            style={{ maxHeight: 400 }}
            showsVerticalScrollIndicator={false}
          >
            {data.map((contact, index) => (
              <View
                key={contact.email || contact.resource_name || String(index)}
              >
                {index > 0 && <View className="h-px bg-zinc-700/50" />}
                <ContactRow contact={contact} />
              </View>
            ))}
          </ScrollView>
        </View>
      ) : (
        <Text className="py-3 text-sm text-zinc-500">No contacts found</Text>
      )}
    </CollapsibleCard>
  );
}
