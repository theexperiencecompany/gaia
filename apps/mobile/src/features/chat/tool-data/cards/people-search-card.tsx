import { ScrollView, View } from "react-native";
import {
  AppIcon,
  Call02Icon,
  Mail01Icon,
  UserSearch01Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { CollapsibleCard } from "@/features/chat/tool-data/primitives";

export interface PeopleSearchData {
  name?: string;
  email?: string;
  phone?: string;
  resource_name?: string;
}

function PersonRow({ person }: { person: PeopleSearchData }) {
  return (
    <View className="flex-row items-start gap-4 p-3">
      {/* Name column — fixed width mirrors web's w-40 */}
      <View className="w-40 shrink-0">
        <Text className="text-sm font-medium text-zinc-300" numberOfLines={1}>
          {person.name}
        </Text>
      </View>

      {/* Details column */}
      <View className="flex-1 min-w-0 gap-1">
        {!!person.email && (
          <View className="flex-row items-center gap-2">
            <AppIcon icon={Mail01Icon} size={14} color="#9ca3af" />
            <Text className="flex-1 text-sm text-zinc-400" numberOfLines={1}>
              {person.email}
            </Text>
          </View>
        )}
        {!!person.phone && (
          <View className="flex-row items-center gap-2">
            <AppIcon icon={Call02Icon} size={14} color="#9ca3af" />
            <Text className="text-sm text-zinc-400">{person.phone}</Text>
          </View>
        )}
      </View>
    </View>
  );
}

export function PeopleSearchCard({ data }: { data: PeopleSearchData[] }) {
  const count = data.length;
  const label = count === 1 ? "Person" : "People";

  return (
    <CollapsibleCard
      icon={UserSearch01Icon}
      iconSize={20}
      title={(open) => `${open ? "Hide" : "Show"} ${count} ${label}`}
      titleTone="muted"
      radius="3xl"
    >
      {count > 0 ? (
        <View className="rounded-3xl bg-zinc-800 p-3">
          <ScrollView
            style={{ maxHeight: 400 }}
            showsVerticalScrollIndicator={false}
          >
            {data.map((person, index) => (
              <View
                key={
                  person.resource_name ||
                  person.email ||
                  person.name ||
                  String(index)
                }
              >
                {index > 0 && <View className="h-px bg-zinc-700" />}
                <PersonRow person={person} />
              </View>
            ))}
          </ScrollView>
        </View>
      ) : (
        <Text className="py-3 text-sm text-zinc-500">No people found</Text>
      )}
    </CollapsibleCard>
  );
}
