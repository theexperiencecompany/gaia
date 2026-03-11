import { Avatar, Card } from "heroui-native";
import { View } from "react-native";
import {
  AppIcon,
  Call02Icon,
  Mail01Icon,
  UserSearch01Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";

export interface PeopleSearchData {
  name?: string;
  email?: string;
  phone?: string;
  organization?: string;
  role?: string;
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

function PersonRow({ person }: { person: PeopleSearchData }) {
  const initials = getInitials(person.name);
  const subtitle =
    person.role && person.organization
      ? `${person.role} · ${person.organization}`
      : person.role || person.organization;

  return (
    <View className="flex-row items-center gap-3 py-2.5 border-b border-white/8 last:border-b-0">
      <Avatar
        alt={person.name ?? initials}
        size="sm"
        className="bg-[#00bbff]/20"
      >
        <Avatar.Fallback className="text-[#00bbff] text-xs font-semibold">
          {initials}
        </Avatar.Fallback>
      </Avatar>
      <View className="flex-1 min-w-0">
        <Text className="text-sm font-medium text-white" numberOfLines={1}>
          {person.name || "Unknown"}
        </Text>
        {!!subtitle && (
          <Text className="text-xs text-[#8e8e93] mt-0.5" numberOfLines={1}>
            {subtitle}
          </Text>
        )}
        <View className="flex-row flex-wrap gap-x-3 mt-0.5">
          {person.email && (
            <View className="flex-row items-center gap-1">
              <AppIcon icon={Mail01Icon} size={11} color="#8e8e93" />
              <Text className="text-xs text-[#8e8e93]" numberOfLines={1}>
                {person.email}
              </Text>
            </View>
          )}
          {person.phone && (
            <View className="flex-row items-center gap-1">
              <AppIcon icon={Call02Icon} size={11} color="#8e8e93" />
              <Text className="text-xs text-[#8e8e93]">{person.phone}</Text>
            </View>
          )}
        </View>
      </View>
    </View>
  );
}

export function PeopleSearchCard({ data }: { data: PeopleSearchData[] }) {
  return (
    <Card variant="secondary" className="mx-4 my-2 rounded-2xl bg-[#171920]">
      <Card.Body className="py-3 px-4">
        <View className="flex-row items-center gap-2 mb-3">
          <AppIcon icon={UserSearch01Icon} size={14} color="#8e8e93" />
          <Text className="text-xs text-[#8e8e93]">People Search</Text>
          <View className="rounded-full bg-white/10 px-2 py-0.5 ml-auto">
            <Text className="text-[10px] text-[#8e8e93]">
              {data.length} {data.length === 1 ? "result" : "results"}
            </Text>
          </View>
        </View>
        <View className="rounded-xl bg-white/5 border border-white/8 px-3 overflow-hidden">
          {data.map((person, index) => (
            <PersonRow
              key={
                person.email ||
                person.resource_name ||
                person.name ||
                String(index)
              }
              person={person}
            />
          ))}
        </View>
      </Card.Body>
    </Card>
  );
}
