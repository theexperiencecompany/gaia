import { ScrollView, View } from "react-native";
import { AppIcon, Call02Icon, Mail01Icon } from "@/components/icons";
import { Text } from "@/components/ui/text";
import { CollapsibleCard } from "@/features/chat/tool-data/primitives";
import { GmailIcon } from "./gmail-icon";

export interface PeopleSearchData {
  name?: string;
  email?: string;
  phone?: string;
  organization?: string;
  role?: string;
  resource_name?: string;
}

// PersonRow mirrors web's row 1:1 (apps/web/src/features/mail/components/PeopleSearchCard.tsx):
//   - Container: items-start gap-4 p-3, no press state (web is cursor-default)
//   - Name column: w-40, text-sm font-medium text-zinc-300 (= web's text-gray-300)
//   - Details column: flex-1, icons at 14px zinc-400 (= web's text-gray-400), text-sm
function PersonRow({ person }: { person: PeopleSearchData }) {
  return (
    <View className="flex-row items-start gap-4 p-3">
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
    </View>
  );
}

export function PeopleSearchCard({ data }: { data: PeopleSearchData[] }) {
  const count = data.length;
  // Matches web CollapsibleListWrapper.getCountLabel for "Person/People" label:
  //   `${count} ${count === 1 ? "Person" : "People"}`
  const label = count === 1 ? "Person" : "People";

  return (
    <CollapsibleCard
      customIcon={<GmailIcon width={20} height={20} />}
      iconSize={20}
      title={(open) => `${open ? "Hide" : "Show"} ${count} ${label}`}
      titleTone="muted"
      radius="3xl"
    >
      {count > 0 ? (
        // Outer container mirrors web's `w-full max-w-2xl rounded-3xl bg-zinc-800 p-3`
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
