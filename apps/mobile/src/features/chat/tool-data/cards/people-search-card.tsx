import { Linking, Pressable, ScrollView, View } from "react-native";
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

// PersonRow mirrors web's group row:
//   - Name column: w-40, text-sm font-medium text-gray-300 (zinc-300)
//   - Details column: flex-1, icons at 14px gray-400 (zinc-400), text-sm
//   - Pressed state: active:bg-zinc-700 (matches web hover:bg-zinc-700)
function PersonRow({ person }: { person: PeopleSearchData }) {
  const handlePress = () => {
    if (person.email) {
      Linking.openURL(`mailto:${person.email}`);
    } else if (person.phone) {
      Linking.openURL(`tel:${person.phone}`);
    }
  };

  const isInteractive = !!(person.email || person.phone);

  return (
    <Pressable
      onPress={isInteractive ? handlePress : undefined}
      className="flex-row items-start gap-4 p-3 active:bg-zinc-700 rounded-xl"
      android_ripple={{ color: "rgba(255,255,255,0.06)" }}
    >
      {/* Name column — fixed width matches web's w-40 */}
      <View className="w-40 shrink-0">
        <Text className="text-sm font-medium text-zinc-300" numberOfLines={1}>
          {person.name}
        </Text>
      </View>

      {/* Details column — email + phone */}
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
    </Pressable>
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
        // Outer container: rounded-3xl bg-zinc-800 p-3 — matches web's container
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
                {/* Divider between rows — matches web's divide-y divide-zinc-700 */}
                {index > 0 && <View className="h-px bg-zinc-700 mx-3" />}
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
